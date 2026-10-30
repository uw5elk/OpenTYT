# -*- coding: utf-8 -*-
"""R38: майстер самоперевірки -- сценарії, які машина проходить краще за людину (прочитати, записати, перечитати, звірити, повернути як було).

Ядро без Tk: панель `cps_ui/p_selfcheck.py` лише викликає `run()`. Рація потрібна лише як `CpsLink` (тести підставляють FakeRadioX).

Сценарії (кожен має позначку ризику):
  лише читання (read)  S2.1 розділи кодплага · S2.2 теми й .gtm · S2.3 бекапи й SHA-256 · S2.4 область custom-data · S2.5 ключі AES (лише номери слотів)
                       S2.6 база позивних (заголовок) · S2.7 голосові підказки (заголовок) · S2.8 назви з малою «я» · S3 знімок екрана проти передпоказу
  пишуть у рацію (write) S4.1 тема · S4.2 VFO · S4.3 канал «Зоря» і контакт «Надія» · S4.4 блок custom-data
  Ключі AES (S4.5) НЕ чіпаються взагалі: перевірка ключів лишається ручною.

Правила безпеки (брифи R38):
  * записи ЛИШЕ після повного знімка у файл (`take_snapshot`): без нього `run()` відмовляє для будь-якого сценарію запису;
  * сценарій запису = запам'ятати -> записати відоме -> перечитати -> звірити -> ПОВЕРНУТИ як було -> звірити ще раз; невдале повернення піднімається ГОЛОСНО
    (`Ctx.loud`) з посиланням на страхову копію;
  * область custom-data пишеться лише через `flash_guard.write_span` (вікно `customdata`: у `guarded_customdata_writes` підміняється `custom_data.flash_write_span`),
    кодплаг -- через `cps_csv.write_image_via_restore` (cps_restore), план якого додатково перевіряє `_plan_guard` за зонами `flash_guard.ZONES`
    (калібрування, custom-data, база позивних, підказки, ключі AES недосяжні);
  * калібрування, таблиця ключів AES, заголовки бази позивних і підказок до і після запису порівнюються (`invariants`): будь-яка зміна -- провал;
  * жоден сценарій не друкує ключів AES: у звіті лише номери слотів і збіг/розбіжність SHA-256.
Звіт -- Markdown `selfcheck_РРРР-ММ-ДД_ГГ-ХХ.md` (крок, очікувано / отримано, результат, час) + перелік ручних кроків (S5)."""
import collections
import contextlib
import datetime
import hashlib
import io
import json
import os
import struct
import time
import traceback
import zipfile

import codeplug_edit as ced
import codeplug_view as cv
import contact_edit as ce
import cps_csv as cc
import cps_link as cl
import cps_restore as rs
import custom_compact as ccmp
import custom_data as cd
import custom_region as cr
import flash_guard as fg
import theme_edit as te
import vfo_edit as ve

RISK_READ = "read"
RISK_WRITE = "write"
RISK_TEXT = {RISK_READ: "лише читання", RISK_WRITE: "ПИШЕ в рацію"}

PASS, FAIL, ERROR, SKIPPED, INTERRUPTED = "pass", "fail", "error", "skipped", "interrupted"
STATUS_TEXT = {PASS: "ПРОЙДЕНО", FAIL: "НЕ ПРОЙДЕНО", ERROR: "ПОМИЛКА", SKIPPED: "ПРОПУЩЕНО", INTERRUPTED: "ОБІРВАНО"}

SECTOR = 4096
MAX_CODEPLUG_SECTORS = 12          # скільки секторів кодплага сценарій може змінити за один запис (більше -- план відхиляється)
TEST_FREQ = ("145.5", "145.6")     # S4.2: «відоме значення» VFO; береться перше, що відрізняється від поточного

CHANNEL_NAME_TEST = "Зоря"
CONTACT_NAME_TEST = "Надія"
CONTACT_ID_TEST = 4380


class SelfcheckError(cl.CpsError):
    """Прогін відхилено ДО будь-якого запису (нема знімка, не підтверджено тощо)."""


# =============================================================================================================================
#  Результати
# =============================================================================================================================

class Step:
    __slots__ = ("name", "expected", "got", "ok", "seconds", "note")

    def __init__(self, name, expected, got, ok, seconds, note=""):
        self.name, self.expected, self.got, self.ok, self.seconds, self.note = name, expected, got, ok, seconds, note


_AUTO = object()


class Result:
    """Підсумок одного сценарію. ok кроку: True -- збіг, False -- розбіжність, None -- довідково (у підсумок не входить)."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.steps = []
        self.notes = []
        self.artifacts = []         # [(підпис, шлях)]
        self.error = None           # текст винятку (status ERROR)
        self.skip_reason = None
        self.interrupted = False
        self.seconds = 0.0
        self._t = time.time()

    def check(self, name, expected, got, ok=_AUTO, note=""):
        """Крок. ok не задано -- порівнюємо expected == got; ok=None -- довідково (у підсумок не входить)."""
        now = time.time()
        if ok is _AUTO:
            ok = (expected == got)
        self.steps.append(Step(name, expected, got, ok, round(now - self._t, 2), note))
        self._t = now
        return ok is not False

    def info(self, name, got, note=""):
        return self.check(name, "(довідково)", got, None, note)

    @property
    def status(self):
        if self.skip_reason is not None:
            return SKIPPED
        if self.interrupted:
            return INTERRUPTED
        if self.error:
            return ERROR
        if any(s.ok is False for s in self.steps):
            return FAIL
        return PASS

    def failed_steps(self):
        return [s for s in self.steps if s.ok is False]


class Scenario:
    def __init__(self, sid, title, risk, func, writes=(), closes=(), default_on=None):
        self.sid, self.title, self.risk, self.func = sid, title, risk, func
        self.writes = tuple(writes)          # перелік змін для підтвердження (лише risk == write)
        self.closes = tuple(closes)          # номери чек-листа, які сценарій закриває повністю або частково
        self.default_on = (risk == RISK_READ) if default_on is None else default_on


# =============================================================================================================================
#  Контекст
# =============================================================================================================================

def _sha(data):
    return hashlib.sha256(bytes(data)).hexdigest()


def _short(h):
    return h[:12]


class Ctx:
    """Усе, що потрібно сценаріям: зв'язок, тека прогону, журнал, кеш читань, знімок, список записів (аудит)."""

    def __init__(self, link, out_dir, log=print, progress=None, now=None, clock=time.time, stamp=None, post_reset=True):
        self.link = link
        self.out_dir = out_dir
        self.log = log
        self._progress = progress
        self.now = now
        self.clock = clock
        self.post_reset = post_reset
        self.stamp = stamp or (now or datetime.datetime.now()).strftime("%Y-%m-%d_%H-%M")
        self.run_dir = os.path.join(out_dir, "selfcheck_%s_files" % self.stamp)
        self.snapshot = None            # {"path", "sha256", "parts", "created"} після take_snapshot
        self.loud = []                  # голосні попередження (невдале повернення, обрив): виносяться на початок звіту
        self.audit = []                 # [(тег, що записано)] -- усе, що сценарії записали
        self.codeplug_written = False   # чи показували на рації екран CPS (тоді в кінці перезавантаження)
        self.halted = None              # текст, якщо запис далі небезпечний (рація в проміжному стані)
        self._cp = None
        self.sc_label = ""
        self.choose = None              # R39 (S3): (заголовок, текст, [підписи]) -> індекс або None; панель підставляє діалог вибору зі списку

    # --- ведення ---
    def progress(self, pct, text=""):
        if self._progress:
            self._progress(max(0, min(100, int(pct))), text)

    def sub_progress(self, lo, hi, prefix=""):
        def cb(pct, text=""):
            self.progress(lo + (hi - lo) * pct / 100.0, (prefix + " " + text).strip())
        return cb

    def mkdir(self):
        os.makedirs(self.run_dir, exist_ok=True)
        return self.run_dir

    def shout(self, text):
        self.loud.append(text)
        self.log("!!! " + text)

    # --- кеш читання кодплага (read-only сценарії діляться одним читанням) ---
    def codeplug(self):
        if self._cp is None:
            cp, _m = cv.codeplug_from_radio(self.link, self.sub_progress(0, 100, "Читаю кодплаг:"))
            self._cp = cp
        return self._cp

    def invalidate(self):
        self._cp = None

    def snapshot_ok(self):
        s = self.snapshot
        return bool(s and s.get("path") and os.path.isfile(s["path"]))


# =============================================================================================================================
#  Знімок (обов'язковий перед записом)
# =============================================================================================================================

def take_snapshot(ctx):
    """Повний знімок у файл: кодплаг + custom-data + ключі AES + голосові підказки + база позивних. Перечитується з диска й звіряється за маніфестом.
    Файл СЕКРЕТНИЙ (є ключі AES). Повертає словник знімка (також у ctx.snapshot)."""
    ctx.mkdir()
    ctx.log("Повний знімок рації (кодплаг, custom-data, ключі AES, голосові підказки, база позивних)...")
    data, manifest = cl.backup_codeplug(ctx.link, ctx.sub_progress(0, 100, "Знімок:"), clock=ctx.clock, log=ctx.log, full_snapshot=True, aes_keys=True,
                                        custom_data=True)
    path = cl.unique_path(ctx.run_dir, cl.timestamp_name("selfcheck_snapshot", ".zip", ctx.now))
    with open(path, "xb") as f:
        f.write(data)
    with open(path, "rb") as f:
        if f.read() != data:
            raise SelfcheckError("знімок записано з розбіжністю читання-запису: %s" % path)
    m2, _ee, _fl = cl.read_backup_zip(path)             # перевіряє SHA-256 і довжини кожної частини
    need = {"eeprom", "flash", "customData", "aesKeys", "voicePrompts", "dmrIdDb"}
    missing = sorted(need - set(m2["parts"]))
    if missing:
        raise SelfcheckError("у знімку бракує частин: %s -- записи недоступні" % ", ".join(missing))
    ctx.snapshot = {"path": path, "sha256": _sha(data), "parts": sorted(m2["parts"]), "created": m2.get("createdUtc", ""),
                    "slots": list(m2["parts"]["aesKeys"].get("occupiedSlots", []))}
    ctx.log("Знімок збережено й перевірено: %s (СЕКРЕТ: містить ключі AES)." % path)
    return ctx.snapshot


# =============================================================================================================================
#  Допоміжне: охоронці запису
# =============================================================================================================================

@contextlib.contextmanager
def guarded_customdata_writes(ctx, tag):
    """Усі записи custom_data.flash_write_span у цьому блоці йдуть через flash_guard.write_span (вікно `customdata`) і заносяться в аудит."""
    orig = cd.flash_write_span

    def guarded(ser, addr, data):
        n = fg.write_span(ser, addr, data, "customdata")
        ctx.audit.append((tag, "custom-data 0x%X..0x%X (%d Б, секторів %d)" % (addr, addr + len(data) - 1, len(data), n)))
        return n

    cd.flash_write_span = guarded
    try:
        yield
    finally:
        cd.flash_write_span = orig


def _plan_guard(ctx, tag, max_sectors=MAX_CODEPLUG_SECTORS):
    """confirm для cps_restore: сценарій уже підтверджений користувачем, тож тут лише перевірка ПЛАНУ -- сектори мають лежати в EEPROM-кодплазі (крім
    калібрування) або у флеш-кодплазі, і їх небагато. Інакше запис відхиляється (нічого не записано)."""
    rng = cl.flash_backup_range()

    def confirm(_text, plan):
        if len(plan.sectors) > max_sectors:
            ctx.shout("%s: план змінює %d секторів (дозволено не більше %d) -- запис ВІДХИЛЕНО, рація не змінена." % (tag, len(plan.sectors), max_sectors))
            return False
        for label, raw_addr, _sec in plan.sectors:
            lo, hi = raw_addr, raw_addr + SECTOR
            if label == "EEPROM":
                ok = hi <= cl.EEPROM_BACKUP_LEN and not (lo < fg.ZONES["calibration"][1] and hi > fg.ZONES["calibration"][0])
            else:
                ok = rng["raw_start"] <= lo and hi <= rng["raw_end"]
                ok = ok and not any(lo < z[1] and hi > z[0] for k, z in fg.ZONES.items() if k != "codeplug")
            if not ok:
                ctx.shout("%s: сектор %s 0x%X поза дозволеними межами -- запис ВІДХИЛЕНО, рація не змінена." % (tag, label, raw_addr))
                return False
        ctx.audit.append((tag, "кодплаг: секторів %d (%s)" % (len(plan.sectors), ", ".join("%s 0x%X" % (s[0], s[1]) for s in plan.sectors))))
        ctx.codeplug_written = True
        return True

    return confirm


def _diff_ranges(a, b):
    """[(початок, кінець)] різних байтів двох рядків однакової довжини."""
    out = []
    start = None
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            if start is None:
                start = i
        elif start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, min(len(a), len(b))))
    return out


def _revert_bytes(orig, edited, current):
    """`current` з поверненими до `orig` лише тими байтами, які змінив сценарій (різниця orig/edited). Решта (що рація змінила сама) не чіпається."""
    out = bytearray(current)
    for s, e in _diff_ranges(orig, edited):
        out[s:e] = orig[s:e]
    return bytes(out)


def _ranges_text(ranges, limit=4):
    t = ", ".join("0x%X..0x%X" % (s, e - 1) for s, e in ranges[:limit])
    return t + (" і ще %d" % (len(ranges) - limit) if len(ranges) > limit else "")


def _write_image(ctx, edit_res, tag, prefetched, note):
    """Записати `edit_res.image` через шлях відновлення. Без перезавантаження (його робить прогін один раз у кінці)."""
    return cc.write_image_via_restore(ctx.link, edit_res, _plan_guard(ctx, tag), progress=ctx.sub_progress(0, 100, tag), log=ctx.log, now=ctx.now,
                                      clock=ctx.clock, post_reset=False, title="САМОПЕРЕВІРКА (%s)" % tag, out_dir=ctx.mkdir(),
                                      zip_prefix="selfcheck_" + tag.replace(".", "_").replace(" ", "_"), note=note, prefetched=prefetched)


def _loud_restore_failure(ctx, res, what, err, safety=None):
    safety_text = ("Страхова копія стану ПЕРЕД цим сценарієм: %s. " % safety) if safety else ""
    snap = ("Повний знімок на початку прогону: %s. " % ctx.snapshot["path"]) if ctx.snapshot else ""
    msg = ("%s: ПОВЕРНЕННЯ ДО ПОЧАТКОВОГО СТАНУ НЕ ВДАЛОСЬ (%s). РАЦІЯ МОЖЕ БУТИ У ЗМІНЕНОМУ СТАНІ. %s%sВідновіть кодплаг з цього файла: Рація -> Бекап -> «Відновити кодплаг...»."
           % (res.scenario.sid, err, safety_text, snap))
    ctx.shout(msg)
    ctx.halted = "рація у проміжному стані після %s" % res.scenario.sid
    res.notes.append("УВАГА! " + msg)


def _latest_safety(ctx):
    """Найновіша страхова копія `codeplug_pre-restore_*.zip` у теці прогону (для повідомлень про збій)."""
    try:
        files = sorted(f for f in os.listdir(ctx.run_dir) if f.startswith("codeplug_pre-restore"))
    except OSError:
        return None
    return os.path.join(ctx.run_dir, files[-1]) if files else None


def _roundtrip(ctx, res, tag, build, verify, note, expect_sectors=None):
    """Спільна схема сценаріїв запису кодплага.
    build(img) -> ImportResult з новим образом; verify(img_after, res) -- семантична перевірка того, що рація тепер має."""
    link = ctx.link
    ctx.progress(0, tag + ": читаю початковий стан")
    cp0, _m = cv.codeplug_from_radio(link, ctx.sub_progress(0, 15, tag + ":"))
    orig = cc.Image.from_codeplug(cp0)
    orig_ee, orig_fl = bytes(orig.eeprom), bytes(orig.flash)
    res.check("початковий стан запам'ятано", "EEPROM %d Б, флеш %d Б" % (cl.EEPROM_BACKUP_LEN, cl.flash_backup_range()["length"]),
              "EEPROM %d Б, флеш %d Б" % (len(orig_ee), len(orig_fl)))
    try:
        edit_res = build(orig)
    except (cl.CpsError, ValueError, LookupError, KeyError) as e:
        res.check("тестовий образ зібрано", "образ зібрано", "відмова: %s" % e, False)
        return None
    edit_ee, edit_fl = bytes(edit_res.image.eeprom), bytes(edit_res.image.flash)
    res.check("тестовий образ відрізняється від поточного", "є зміни", "є зміни" if (edit_ee, edit_fl) != (orig_ee, orig_fl) else "змін нема",
              (edit_ee, edit_fl) != (orig_ee, orig_fl))
    # --- запис ---
    try:
        out = _write_image(ctx, edit_res, tag + " запис", (orig_ee, orig_fl), note)
    except rs.RestoreRefused as e:
        res.check("запис тестового значення", "записано й звірено", "відмова ДО запису: %s" % e, False)
        return None
    except (rs.RestoreInterrupted, rs.RestoreVerifyFailed, cl.CpsError) as e:
        res.check("запис тестового значення", "записано й звірено", str(e).splitlines()[0], False, "повний текст: " + " / ".join(str(e).splitlines()[1:4]))
        res.interrupted = isinstance(e, rs.RestoreInterrupted)
        _rollback(ctx, res, tag, orig_ee, orig_fl, edit_ee, edit_fl)
        return None
    if out.get("cancelled"):
        res.check("запис тестового значення", "записано", "план відхилено охоронцем", False)
        return None
    if out.get("nothingToDo"):
        res.check("запис тестового значення", "рація отримала нове значення", "рація вже містила цей образ: запис нічого не змінив, сценарій нічого не довів", False)
        return None
    exp_ee, exp_fl = _sha(rs._mask_unstable(edit_ee)), _sha(edit_fl)
    res.check("запис і звірка SHA-256 (cps_restore)", "EEPROM %s, флеш %s" % (_short(exp_ee), _short(exp_fl)),
              "EEPROM %s, флеш %s" % (_short(out["sha256Eeprom"]), _short(out["sha256Flash"])), out["sha256Eeprom"] == exp_ee and out["sha256Flash"] == exp_fl,
              "записано секторів: %d" % out["sectorsWritten"])
    if expect_sectors is not None:
        res.check("змінено лише потрібні сектори", "не більше %d" % expect_sectors, str(out["sectorsWritten"]), out["sectorsWritten"] <= expect_sectors)
    # --- перечитати й перевірити зміст ---
    ctx.progress(55, tag + ": перечитую")
    try:
        cp1, _m = cv.codeplug_from_radio(link, ctx.sub_progress(55, 70, tag + ":"))
    except cl.CpsError as e:
        res.check("перечитування після запису", "кодплаг прочитано", str(e), False)
        _rollback(ctx, res, tag, orig_ee, orig_fl, edit_ee, edit_fl)
        return None
    cur1 = cc.Image.from_codeplug(cp1)
    verify(cur1, res)
    # --- повернути як було ---
    rev_ee = _revert_bytes(orig_ee, edit_ee, bytes(cur1.eeprom))
    rev_fl = _revert_bytes(orig_fl, edit_fl, bytes(cur1.flash))
    back = cc.ImportResult()
    back.image = cc.Image(bytearray(rev_ee), bytearray(rev_fl), orig.base)
    back.changed.append(("Самоперевірка", "повернення початкового стану (%s)" % tag))
    try:
        out2 = _write_image(ctx, back, tag + " повернення", (bytes(cur1.eeprom), bytes(cur1.flash)), "Повернення до стану, який був до сценарію %s." % tag)
    except (cl.CpsError, rs.RestoreInterrupted, rs.RestoreVerifyFailed, rs.RestoreRefused) as e:
        res.check("повернення початкового стану", "повернуто й звірено", str(e).splitlines()[0], False)
        res.interrupted = res.interrupted or isinstance(e, rs.RestoreInterrupted)
        _loud_restore_failure(ctx, res, "повернення", str(e).splitlines()[0], _latest_safety(ctx))
        return None
    if out2.get("cancelled"):
        res.check("повернення початкового стану", "повернуто", "план відхилено охоронцем", False)
        _loud_restore_failure(ctx, res, "повернення", "план відхилено охоронцем", _latest_safety(ctx))
        return None
    if out2.get("nothingToDo"):                      # рація вже збігається з тим, що мало бути: читаємо хеші з уже зробленого перечитування
        out2 = dict(out2, sha256Eeprom=_sha(rs._mask_unstable(bytes(cur1.eeprom))), sha256Flash=_sha(bytes(cur1.flash)), sectorsWritten=0)
    exp2_ee, exp2_fl = _sha(rs._mask_unstable(rev_ee)), _sha(rev_fl)
    res.check("повернення: запис і звірка SHA-256", "EEPROM %s, флеш %s" % (_short(exp2_ee), _short(exp2_fl)),
              "EEPROM %s, флеш %s" % (_short(out2["sha256Eeprom"]), _short(out2["sha256Flash"])),
              out2["sha256Eeprom"] == exp2_ee and out2["sha256Flash"] == exp2_fl, "записано секторів: %d" % out2["sectorsWritten"])
    # повернено ТЕ САМЕ, що було до сценарію (EEPROM без нестабільних ділянок)
    same_fl = out2["sha256Flash"] == _sha(orig_fl)
    same_ee = out2["sha256Eeprom"] == _sha(rs._mask_unstable(orig_ee))
    ok = same_fl and same_ee
    res.check("повернення: рація ТАКА САМА, як до сценарію", "SHA-256 збігається з початковим (EEPROM без ділянок, що рація міняє сама, і флеш)",
              "збігається" if ok else "РОЗБІЖНІСТЬ: %s" % ", ".join(n for n, f in (("EEPROM", same_ee), ("флеш", same_fl)) if not f), ok)
    if not ok:
        _loud_restore_failure(ctx, res, "звірка", "після повернення рація відрізняється від початкового стану", _latest_safety(ctx))
    return out2


def _rollback(ctx, res, tag, orig_ee, orig_fl, edit_ee, edit_fl):
    """Аварійне повернення після збою запису/перечитування: свіже читання -> повернути лише змінене сценарієм. Невдача -- голосно."""
    ctx.log("%s: збій -- пробую повернути початковий стан..." % tag)
    safety = _latest_safety(ctx)
    try:
        cp, _m = cv.codeplug_from_radio(ctx.link, ctx.sub_progress(70, 80, tag + " відкат:"))
    except cl.CpsError as e:
        res.check("аварійне повернення", "початковий стан повернуто", "рація не відповідає: %s" % e, False)
        _loud_restore_failure(ctx, res, "аварійне повернення", "рація не відповідає: %s" % e, safety)
        return
    cur = cc.Image.from_codeplug(cp)
    ee = _revert_bytes(orig_ee, edit_ee, bytes(cur.eeprom))
    fl = _revert_bytes(orig_fl, edit_fl, bytes(cur.flash))
    if (ee, fl) == (bytes(cur.eeprom), bytes(cur.flash)):
        res.check("аварійне повернення", "початковий стан", "рація вже у початковому стані (запис не дійшов до флеша)", True)
        return
    back = cc.ImportResult()
    back.image = cc.Image(bytearray(ee), bytearray(fl), cur.base)
    back.changed.append(("Самоперевірка", "аварійне повернення (%s)" % tag))
    try:
        _write_image(ctx, back, tag + " аварійне повернення", (bytes(cur.eeprom), bytes(cur.flash)), "Аварійне повернення початкового стану.")
    except (cl.CpsError, rs.RestoreInterrupted, rs.RestoreVerifyFailed, rs.RestoreRefused) as e:
        res.check("аварійне повернення", "початковий стан повернуто", str(e).splitlines()[0], False)
        _loud_restore_failure(ctx, res, "аварійне повернення", str(e).splitlines()[0], safety)
        return
    res.check("аварійне повернення", "початковий стан повернуто", "повернуто й звірено", True)
    res.notes.append("Тестовий запис не вдався, але початковий стан повернуто автоматично (страхова копія: %s)." % (safety or "?"))


# =============================================================================================================================
#  Інваріанти: те, чого сценарії запису торкатись не можуть
# =============================================================================================================================

def snapshot_invariants(link):
    """SHA-256 того, що сценарії зобов'язані лишити як було: калібрування, ключі AES, заголовок бази позивних, заголовок підказок.
    Ключі читаються лише для хеша (у звіт потрапляє тільки збіг/розбіжність)."""
    import aes_keys_backup as akb
    import dmr_db
    import voice_prompts as vp
    out = {}
    for name, fn in (("калібрування 0x10000..0x10FFF", lambda: link.read(cl.CPS_ACCESS_EEPROM, 0x10000, SECTOR)),
                     ("таблиця ключів AES", lambda: akb.read_radio_keys(link)),
                     ("заголовок бази позивних", lambda: link.read(cl.CPS_ACCESS_FLASH, dmr_db.AREA1_START, dmr_db.HEADER_LEN)),
                     ("заголовок голосових підказок", lambda: link.read(cl.CPS_ACCESS_FLASH, vp.VP_START, vp.DATA_BASE))):
        try:
            out[name] = _sha(fn())
        except cl.CpsError as e:
            out[name] = "не прочитано: %s" % e
    return out


def invariants_result(before, after):
    r = Result(Scenario("S4.0", "Інваріанти: що сценарії запису не мали чіпати", RISK_READ, None))
    for name in before:
        b, a = before[name], after.get(name, "?")
        bad_read = b.startswith("не прочитано") or a.startswith("не прочитано")
        r.check(name + ": до і після", "SHA-256 однакові", "однакові (%s)" % _short(b) if b == a else ("не вдалося прочитати: %s / %s" % (b[:30], a[:30]) if bad_read else
                                                                                                 "ЗМІНИЛОСЬ: %s -> %s" % (_short(b), _short(a))),
                b == a and not bad_read)
    return r


# =============================================================================================================================
#  S2: лише читання
# =============================================================================================================================

def s2_1(ctx, res):
    cp = ctx.codeplug()
    img = cc.Image.from_codeplug(cp)
    rows = cc.export_rows(img, ".")
    basic = ced.basic_values(img)
    res.check("позивний: перегляд = форма «Основна інформація»", basic["callsign"], cp.callsign(), basic["callsign"] == cp.callsign(), "позивний: «%s»" % cp.callsign())
    res.check("DMR ID: перегляд = форма «Основна інформація»", basic["dmr_id"], cp.dmr_id())
    pairs = [
        ("канали", len(cp.channels()), len(img.channels()), len(rows["channels"][1]), cp.channel_count()),
        ("контакти", len(cp.contacts()), len(img.contacts()), len(rows["contacts"][1]), None),
        ("списки TG", len(cp.rx_groups()), len(img.groups()), len(rows["tg_lists"][1]), None),
        ("зони", len(cp.zones()), len(img.zones()), len(rows["zones"][1]), None),
        ("слоти APRS", None, len(img.aprs()), len(rows["aprs"][1]), None),
        ("слоти DTMF", None, len(img.dtmf()), len(rows["dtmf"][1]), None),
    ]
    for label, view, image, csv, popcount in pairs:
        vals = [v for v in (view, image, csv, popcount) if v is not None]
        res.check("кількість: %s -- розділ, образ, CSV%s" % (label, ", лічильник бітів" if popcount is not None else ""), "усі однакові",
                  " / ".join(str(v) for v in vals), len(set(vals)) == 1, "")
    # імена: перегляд і CSV (колонка «читабельна») -- ті самі
    bad = []
    chan_view = {n: t for n, t, _e, _a, _b, _m in cp.channels()}
    for (n, _rec), row in zip(img.channels(), rows["channels"][1]):
        if chan_view.get(n) != row[-1]:
            bad.append("канал %d: «%s» / «%s»" % (n, chan_view.get(n), row[-1]))
    con_view = {n: t for n, t, *_r in cp.contacts()}
    for (slot, _rec), row in zip(img.contacts(), rows["contacts"][1]):
        if con_view.get(slot + 1) != row[-1]:
            bad.append("контакт %d: «%s» / «%s»" % (slot + 1, con_view.get(slot + 1), row[-1]))
    res.check("назви каналів і контактів: розділ = CSV", "збігаються", "збігаються" if not bad else "; ".join(bad[:3]), not bad)
    res.info("склад кодплага", "каналів %d, контактів %d, списків %d, зон %d, APRS %d, DTMF %d" % (
        len(cp.channels()), len(cp.contacts()), len(cp.rx_groups()), len(cp.zones()), len(img.aprs()), len(img.dtmf())))


def s2_2(ctx, res):
    d = os.path.join(ctx.mkdir(), "themes")
    os.makedirs(d, exist_ok=True)
    for daytime in ("day", "night"):
        name = te.DAYTIME_NAMES[daytime]
        state, colors = te.read_theme(ctx.link.ser, daytime)
        res.info("%s тема: стан у рації" % name.lower(), te.STATE_TEXT[state])
        if colors is None:
            colors = te.stock_colors(daytime)
            res.info("%s тема: кольори" % name.lower(), "блока нема -- рація показує стокову; далі беру стокову (українську гілку)")
        else:
            raw = cd.read_block(ctx.link.ser, te.TYPE_OF[daytime], te.BLOCK_LEN)
            res.check("%s тема: байти блока = розкодовані кольори" % name.lower(), "збігаються", "збігаються" if raw == te.encode_block(colors) else "РОЗБІЖНІ",
                      raw == te.encode_block(colors))
            counts = te.match_counts(colors, daytime)
            res.info("%s тема: збіг зі зашитими палітрами" % name.lower(),
                     "; ".join("%s: %d з %d" % (te.VARIANT_NAMES[k], v, te.ITEM_COUNT) for k, v in counts.items()))
        path = os.path.join(d, "theme_%s.gtm" % daytime)
        saved = te.save_gtm(path, colors)
        with open(path, "rb") as f:
            from_file = f.read()
        res.check("%s тема: файл .gtm побайтово = блок" % name.lower(), "64 байти, збігаються", "%d байтів, %s" % (len(from_file), "збігаються" if from_file == saved else "РОЗБІЖНІ"),
                  len(from_file) == te.BLOCK_LEN and from_file == saved == te.encode_block(colors))
        try:
            back = te.load_gtm(path)
        except te.GtmError as e:
            res.check("%s тема: .gtm перечитується" % name.lower(), "32 кольори", str(e), False)
            continue
        res.check("%s тема: з файла ті самі 32 кольори" % name.lower(), "ті самі", "ті самі" if back == list(colors) else "ІНШІ", back == list(colors))
        res.artifacts.append(("тема %s" % name.lower(), path))


def s2_3(ctx, res):
    import aes_keys_backup as akb
    d = ctx.mkdir()
    # --- звичайний бекап ---
    data, m1 = cl.backup_codeplug(ctx.link, ctx.sub_progress(0, 60, "Бекап:"), clock=ctx.clock, log=ctx.log, full_snapshot=False, aes_keys=True, custom_data=True)
    p1 = cl.unique_path(d, cl.timestamp_name("selfcheck_backup", ".zip", ctx.now))
    with open(p1, "xb") as f:
        f.write(data)
    res.artifacts.append(("звичайний бекап (секрет: ключі AES)", p1))
    _check_archive(res, p1, "звичайний бекап", {"eeprom", "flash", "customData", "aesKeys"}, {"voicePrompts", "dmrIdDb"})
    _m, ee, fl = cl.read_backup_zip(p1)
    # --- повний знімок: беремо зроблений на початку, інакше робимо ---
    if ctx.snapshot_ok():
        p2 = ctx.snapshot["path"]
        res.info("повний знімок", "беру зроблений на початку прогону: %s" % os.path.basename(p2))
    else:
        s = take_snapshot(ctx)
        p2 = s["path"]
    _check_archive(res, p2, "повний знімок", {"eeprom", "flash", "customData", "aesKeys", "voicePrompts", "dmrIdDb"}, set())
    m2, ee2, fl2 = cl.read_backup_zip(p2)
    res.check("звичайний і повний: однаковий флеш-кодплаг", "збігається", "збігається" if fl == fl2 else "РОЗБІЖНИЙ", fl == fl2)
    res.check("звичайний і повний: EEPROM (без ділянок, що рація міняє сама)", "збігається", "збігається" if rs._mask_unstable(ee) == rs._mask_unstable(ee2) else "РОЗБІЖНИЙ",
              rs._mask_unstable(ee) == rs._mask_unstable(ee2))
    # --- у маніфесті лише НОМЕРИ слотів ---
    keys = akb.read_backup_keys(p2)
    part = m2["parts"]["aesKeys"]
    text = json.dumps(m2, ensure_ascii=False)
    leak = [s for s in part["occupiedSlots"] if keys and akb.entry_of(keys, s)[:16].hex() in text]
    res.check("маніфест ключів AES: лише номери слотів", "номери слотів %s, ключових байтів нема" % akb.slots_text(part["occupiedSlots"]),
              "номери слотів %s, %s" % (akb.slots_text(part["occupiedSlots"]), "ключові байти ВИТЕКЛИ у маніфест" if leak else "ключових байтів нема"), not leak)
    del keys
    # --- бекап без ключів (дешево: EEPROM і флеш беремо з першого) ---
    data3, m3 = cl.backup_codeplug(ctx.link, ctx.sub_progress(60, 95, "Бекап без ключів:"), clock=ctx.clock, log=ctx.log, aes_keys=False, custom_data=True,
                                   prefetched=(ee, fl))
    with zipfile.ZipFile(io.BytesIO(data3)) as z:
        names = set(z.namelist())
    res.check("бекап без ключів: файла aeskeys.bin нема, частини aesKeys нема", "нема", "%s / %s" % ("aeskeys.bin є" if akb.PART_FILE in names else "aeskeys.bin нема",
              "частина є" if akb.PART_KEY in m3["parts"] else "частини нема"), akb.PART_FILE not in names and akb.PART_KEY not in m3["parts"])
    cl.read_backup_zip(data3)       # цілісність (кине CpsError, якщо ні)


def _check_archive(res, path, label, must, forbidden):
    try:
        manifest, _ee, _fl = cl.read_backup_zip(path)
    except cl.CpsError as e:
        res.check("%s: архів читається, SHA-256 за маніфестом" % label, "гаразд", str(e), False)
        return
    res.check("%s: архів читається, довжини й SHA-256 за маніфестом" % label, "гаразд", "гаразд", True)
    parts = set(manifest["parts"])
    res.check("%s: склад за маніфестом" % label, ", ".join(sorted(must)), ", ".join(sorted(parts)), must <= parts and not (forbidden & parts))
    with zipfile.ZipFile(path) as z:
        for key in sorted(parts):
            p = manifest["parts"][key]
            fname = p.get("file", key + ".bin")
            if key in ("eeprom", "flash"):
                fname = key + ".bin"
            try:
                got = _sha(z.read(fname))
            except KeyError:
                res.check("%s: частина %s" % (label, key), "SHA-256 %s" % _short(p["sha256"]), "файла %s в архіві нема" % fname, False)
                continue
            res.check("%s: частина %s -- SHA-256 файла = маніфест" % (label, key), _short(p["sha256"]), _short(got), got == p["sha256"],
                      "%d Б" % p["length"])


def s2_4(ctx, res):
    data = cr.read_radio_region(ctx.link)
    scan, st = ccmp.stats_of(data)
    res.check("область custom-data: заголовок OpenGD77", "є", "є" if scan.magic_ok else "нема: %s" % "; ".join(scan.problems), scan.magic_ok)
    if st is None:
        res.check("область custom-data розібрана без проблем", "без проблем", "; ".join(scan.problems) or "не розібрана", False)
        return
    res.check("область розібрана без проблем", "без проблем", "без проблем" if not scan.problems else "; ".join(scan.problems), not scan.problems)
    res.check("зайнято + вільно = вся область", "%d Б" % st.total, "%d Б" % (st.used + st.free), st.used + st.free == st.total)
    res.check("зайнято = заголовок + живі + вилучені блоки + затінені дублікати", "%d Б" % st.used,
              "%d Б" % (ccmp.REGION_HDR + st.live_bytes + st.retired_bytes), st.used == ccmp.REGION_HDR + st.live_bytes + st.retired_bytes)
    res.info("зайнято / вільно / вилучено", "зайнято %d Б, вільно %d Б, вилучено %d Б (%d блоків); живих %d Б (%d блоків)" % (
        st.used, st.free, st.retired_bytes, st.retired_count, st.live_bytes, st.live_count))
    for e in scan.entries:
        res.info("блок @%d" % e.offset, "%s, %d Б%s" % (cr.type_title(e.type), e.length, ", ВИЛУЧЕНИЙ" if e.retired else ""))
    if ctx.snapshot_ok():
        snap_blocks = None
        try:
            with zipfile.ZipFile(ctx.snapshot["path"]) as z:
                reg = z.read(cr.PART_FILE)
            snap_blocks = [(e.type, e.length) for e in ccmp.scan_region(reg).entries]
        except (KeyError, OSError, zipfile.BadZipFile):
            pass
        if snap_blocks is not None:
            now_blocks = [(e.type, e.length) for e in scan.entries]
            res.check("перелік блоків = перелік у знімку", "збігається", "збігається" if now_blocks == snap_blocks else "ІНШИЙ (рація змінилась після знімка)",
                      now_blocks == snap_blocks)


def s2_5(ctx, res):
    import aes_keys_backup as akb
    keys = akb.read_radio_keys(ctx.link)
    res.check("таблиця ключів AES: довжина", "%d Б" % akb.KEYS_LEN, "%d Б" % len(keys), len(keys) == akb.KEYS_LEN)
    slots = akb.occupied_slots(keys)
    del keys
    res.info("зайняті слоти AES (лише номери, ключі не показую)", akb.slots_text(slots), "слотів зайнято %d з %d" % (len(slots), akb.SLOT_MAX - akb.SLOT_MIN + 1))
    if ctx.snapshot_ok():
        res.check("зайняті слоти = слоти у знімку", akb.slots_text(ctx.snapshot["slots"]), akb.slots_text(slots), list(ctx.snapshot["slots"]) == list(slots))


def s2_6(ctx, res):
    import dmr_db
    h = dmr_db.read_radio_header(ctx.link)
    if not h.rec_len and not h.valid:
        res.info("база позивних", "бази в рації нема або заголовок не 'Id'", "; ".join(h.problems))
        return
    res.check("база позивних: заголовок розібрано", "без проблем", "без проблем" if h.valid else "; ".join(h.problems), h.valid)
    res.info("база позивних: формат", {"N": "'N' (3-байтний ID, стиснутий текст)", "n": "'n'", "plain": "звичайний (4-байтний ID)"}.get(h.mode, str(h.mode)))
    res.info("база позивних: записів", "%d" % h.count)
    res.info("база позивних: довжина запису", "%d Б" % h.rec_len)
    res.check("база позивних: займає HEADER + записів * довжину", "%d Б" % (dmr_db.HEADER_LEN + h.count * h.rec_len), "%d Б" % h.extent,
              h.extent == dmr_db.HEADER_LEN + h.count * h.rec_len)
    for w in h.warnings:
        res.info("база позивних: попередження", w)


def s2_7(ctx, res):
    import voice_prompts as vp
    info = vp.read_info(ctx.link)
    if not info.magic_ok:
        res.info("голосові підказки", "у рації їх нема (заголовок не 'VP')")
        return
    res.check("підказки: версія", "%d" % vp.VERSION, "%d" % (info.version or 0), info.version == vp.VERSION)
    res.check("підказки: заголовок і таблиця змісту без проблем", "без проблем", "без проблем" if not info.problems else "; ".join(info.problems), not info.problems)
    res.info("підказки: фраз присутні", "%d з %d у таблиці" % (info.present, vp.TOC_SIZE))
    res.info("підказки: обсяг даних", "%d Б" % info.extent)


def _raw_names(ctx):
    """[(розділ, номер, сирі 16 байтів назви)] усіх назв кодплага."""
    img = cc.Image.from_codeplug(ctx.codeplug())
    out = []
    for n, rec in img.channels():
        out.append(("канал", n, bytes(rec[:16])))
    for slot, rec in img.contacts():
        out.append(("контакт", slot + 1, bytes(rec[:16])))
    for bit, rec in img.zones():
        out.append(("зона", bit + 1, bytes(rec[:16])))
    for slot, rec, _l in img.groups():
        out.append(("список TG", slot + 1, bytes(rec[:16])))
    for slot, rec in img.dtmf():
        out.append(("DTMF", slot + 1, bytes(rec[:16])))
    return out


def s2_8(ctx, res):
    names = _raw_names(ctx)
    found = []
    for kind, n, raw in names:
        nb = cv.name_bytes(raw)
        if 0xFF not in nb:
            continue
        tail = raw[len(nb):]
        tail_kind = ("хвіст 0x00" if tail[:1] == b"\x00" else ("без хвоста (16 байтів)" if not tail else "хвіст 0xFF"))
        text = cv.decode_name_ex(raw)[0]
        found.append((kind, n, raw, text, tail_kind, nb[-1:] == b"\xff"))
    res.info("назв у кодплазі", "%d" % len(names))
    if not found:
        res.info("назви з малою «я» (cp1251, байт 0xFF)", "жодної -- перевірка нічого не довела", "додайте контакт «Надія» (чек-лист 1.7) або пройдіть S4.3")
        return
    for kind, n, raw, text, tail_kind, at_end in found:
        ok = "я" in text.lower()
        res.check("%s №%d: «я» читається (%s)" % (kind, n, "в кінці" if at_end else "всередині"), "літера «я» на місці", "«%s», %s, байти %s" % (
            text, tail_kind, raw.hex(" ")), ok)
        if at_end and tail_kind == "хвіст 0xFF":
            res.info("%s №%d: примітка" % (kind, n), "кінцева «я» з хвостом 0xFF, що її не відрізнити від дописки, сюди не потрапила б; цей запис має хвіст 0x00")
    if not any(f[5] for f in found):
        res.info("кінцева «я» (хвіст 0x00)", "серед знайдених назв, що закінчуються на «я», нема -- ця форма (R36) не перевірена на наявних даних; пройдіть S4.3")


# =============================================================================================================================
#  S3: знімок екрана проти передпоказу (R39)
#  Головне -- ПАЛІТРА (усі кольори знімка належать темі, яку рація зберігає) і ЗОНИ (у кожній зоні домінує колір, який їй призначає тема).
#  Піксельна різниця з рендером -- лише довідка: на живій рації частина екрана (сигнал, годинник, заряд, значки) не читається з кодплага.
# =============================================================================================================================
W, H = 160, 128
SCALE = 2
S3_MAX_READS = 8                   # скільки разів читати екран, поки два читання поспіль не збіжаться (R39 E3)

# --- де рація зберігає поточну зону/канал (прочитано з вихідного коду прошивки) ---
LUCZ_ADDR = 0x6000                 # codeplug.h: CODEPLUG_ADDR_LUCZ -- тег «LUCZ» + lastUsedChannelInZoneData[70]
LUCZ_BYTES = 70                    # CODEPLUG_ALL_ZONES_MAX + 1: байт на зону (за БІТОМ зони) + int16 «Всі канали» на зсуві LUCZ_ALL_SLOT
LUCZ_ALL_SLOT = 68                 # SAFE_MIN(-1, 68U) у беззнаковому порівнянні дає 68
SETTINGS_EE_ADDR = 0x6000 + 0x4B   # settingsStorage.c: STORAGE_BASE_ADDRESS -- одразу за блоком LUCZ
SETTINGS_MAGIC = 0x4780            # settings.c: STORAGE_MAGIC_NUMBER
SETTINGS_OFF_CURRENT_ZONE = 58     # offsetof(settingsStruct_t, currentZone) для MDUV380 (LOG_GPS_DATA=1): виміряно gcc на витягу структури з settings.h
ALL_CHANNELS_UA = "Всі канали"     # languages/ukrainian.h: .all_channels (cp1251); звіряється в test_r39

# --- ділянки, яких S3 НЕ порівнює попіксельно, бо їх вигляд визначає стан рації, якого кодплаг не містить (R39 E1.2) ---
# (x1, y1, x2, y2) включно; назва -- для звіту
EXCLUDED_ALWAYS = (
    ("шапка праворуч: заряд, годинник, значки SMS/APRS/GPS", (104, 0, 159, 9)),
    ("блок S-метра: смуга й значення сигналу", (0, 41, 159, 63)),
    ("значок замка AES", (147, 14, 156, 22)),
)
POWER_BOX = (50, 0, 82, 9)          # рядок потужності в шапці: якщо в каналі «Master», потужність береться з налаштувань рації, яких тут не читаємо
CONTACT_BOX = (0, 24, 159, 39)


def _sv():
    import screen_views as sv
    return sv


def capture_stable(link, max_reads=S3_MAX_READS, log=print):
    """Читає екран, доки два читання поспіль не збіжаться (але не більше max_reads). Повертає (дані, стабільний, скільки_читань)."""
    prev = cl.capture_screen(link)
    for n in range(2, max(2, max_reads) + 1):
        cur = cl.capture_screen(link)
        if cur == prev:
            return cur, True, n
        prev = cur
    log("Увага: екран змінювався під час усіх %d читань -- кадр «рваний»." % max_reads)
    return prev, False, max_reads


def screen_words(raw):
    """Знімок рації (160*128*2 Б, RGB565 big-endian) -> список слів."""
    if len(raw) < W * H * 2:
        raise cl.CpsError("знімок неповний: %d байтів із %d" % (len(raw), W * H * 2))
    return list(struct.unpack(">%dH" % (W * H), bytes(raw[:W * H * 2])))


def render_words(display, colors):
    """Передпоказ -> список слів RGB565 тих самих розмірів."""
    return [colors[i] for i in display.px]


# --- поточна зона й канал ---------------------------------------------------------------------------------------------------

def _unknown(why):
    return {"known": False, "why": why}


def read_current_selection(cp):
    """Поточні зона й канал рації з її EEPROM: номер зони -- `nonVolatileSettings.currentZone` (порядковий номер зони серед зон у роботі; остання, віртуальна, --
    «Всі канали»), позиція в зоні -- байт LUCZ за БІТОМ зони (для «Всі канали» -- int16 = номер каналу - 1). Якщо чогось не вдалося прочитати або значення
    поза межами -- known=False з причиною (тоді канал обирає людина, перший канал НЕ підставляється, R39 E1.3).
    Рація зберігає ці значення із затримкою (гіпотеза): щойно перемкнутий канал у EEPROM може ще не бути."""
    ee = cp.eeprom
    need = SETTINGS_EE_ADDR + SETTINGS_OFF_CURRENT_ZONE + 2
    if len(ee) < need or len(ee) < LUCZ_ADDR + 4 + LUCZ_BYTES:
        return _unknown("образ EEPROM коротший за область налаштувань (%d Б)" % len(ee))
    magic = struct.unpack_from("<I", ee, SETTINGS_EE_ADDR)[0]
    if magic != SETTINGS_MAGIC:
        return _unknown("магічне число налаштувань 0x%X, очікувалось 0x%X (налаштування не записані або інша версія прошивки)" % (magic, SETTINGS_MAGIC))
    if bytes(ee[LUCZ_ADDR:LUCZ_ADDR + 4]) != b"LUCZ":
        return _unknown("в EEPROM нема запису «останній канал у зоні» (тег LUCZ)")
    lucz = bytes(ee[LUCZ_ADDR + 4:LUCZ_ADDR + 4 + LUCZ_BYTES])
    zone_pos = struct.unpack_from("<h", ee, SETTINGS_EE_ADDR + SETTINGS_OFF_CURRENT_ZONE)[0]
    zones = cp.zones()
    if zone_pos == len(zones):
        n = struct.unpack_from("<h", lucz, LUCZ_ALL_SLOT)[0] + 1
        if not (1 <= n <= cl.CP_CHANNELS_BANKS * cl.CP_CHANNELS_PER_BANK) or not cp.channel_in_use(n):
            return _unknown("у «Всіх каналах» збережено канал №%d, якого в кодплазі нема" % n)
        return {"known": True, "all": True, "zone_name": ALL_CHANNELS_UA, "zone_pos": zone_pos, "pos_in_zone": n, "channel_no": n,
                "source": "налаштування рації (currentZone=%d, «Всі канали») і LUCZ" % zone_pos}
    if not (0 <= zone_pos < len(zones)):
        return _unknown("поточна зона №%d поза межами 0..%d" % (zone_pos, len(zones)))
    bit1, zname, _enc, chans = zones[zone_pos]
    idx = lucz[bit1 - 1]
    if idx >= len(chans):
        return _unknown("у зоні «%s» збережено позицію %d, а каналів у ній %d" % (zname, idx + 1, len(chans)))
    n = chans[idx]
    if not cp.channel_in_use(n):
        return _unknown("у зоні «%s» позиція %d вказує на канал №%d, якого в кодплазі нема" % (zname, idx + 1, n))
    return {"known": True, "all": False, "zone_name": zname, "zone_pos": zone_pos, "pos_in_zone": idx + 1, "channel_no": n,
            "source": "налаштування рації (currentZone=%d) і LUCZ[біт %d]" % (zone_pos, bit1 - 1)}


def selection_choices(cp):
    """Усі пари «зона -- канал» для ручного вибору: [(підпис, вибір)]. Спершу зони по порядку, наприкінці «Всі канали»."""
    out = []
    names = {n: t for n, t, *_r in cp.channels()}
    for pos, (bit1, zname, _enc, chans) in enumerate(cp.zones()):
        for k, n in enumerate(chans):
            if cp.channel_in_use(n):
                out.append(("%s · №%d в зоні · %s (канал %d)" % (zname, k + 1, names.get(n, "?"), n),
                            {"known": True, "all": False, "zone_name": zname, "zone_pos": pos, "pos_in_zone": k + 1, "channel_no": n, "source": "вибрано вручну"}))
    npos = len(cp.zones())
    for n, text, *_r in cp.channels():
        out.append(("%s · %s (канал %d)" % (ALL_CHANNELS_UA, text, n),
                    {"known": True, "all": True, "zone_name": ALL_CHANNELS_UA, "zone_pos": npos, "pos_in_zone": n, "channel_no": n, "source": "вибрано вручну"}))
    return out


def real_state(cp, sel):
    """Словник стану для screen_views.render з РЕАЛЬНИМИ даними кодплага (E1.1) + список додаткових виключених ділянок (E1.2) + список приміток.
    Усе, чого кодплаг не містить (сигнал, заряд, час, значки), лишається прикладним значенням SAMPLE -- ці ділянки виключаються з порівняння."""
    sv = _sv()
    rec = cp.channel_record(sel["channel_no"])
    st = dict(sv.SAMPLE)
    extra, notes = [], []
    digital = rec[cc.O_MODE] != 0
    st["mode"] = "dmr" if digital else "fm"
    st["zone"] = sel["zone_name"]
    st["channel_no"] = sel["pos_in_zone"]
    st["channel"] = cv.decode_name(bytes(rec[:16]))
    rx, tx = cv.freq_bcd_le(rec[cc.O_RX:cc.O_RX + 4]), cv.freq_bcd_le(rec[cc.O_TX:cc.O_TX + 4])
    if rx:
        st["rx_freq"] = rx
    if tx:
        st["tx_freq"] = tx
    st["ts"] = 2 if rec[cc.O_FLAG2] & cc.F2_TS2 else 1
    st["cc"] = rec[cc.O_COLOR]
    if rec[cc.O_POWER] == 0:
        extra.append(("потужність «Master» (береться з налаштувань рації)", POWER_BOX))
    else:
        st["power"] = cc.power_text(rec[cc.O_POWER])
    if digital:
        cnum = rec[cc.O_CONTACT] | (rec[cc.O_CONTACT + 1] << 8)
        names = {n: t for n, t, *_r in cp.contacts()}
        if cnum and cnum in names:
            st["contact"] = names[cnum]
        else:
            extra.append(("контакт каналу не заданий (що рація показує в цьому рядку -- не змодельовано)", CONTACT_BOX))
    return st, extra, notes


def exclusion_rects(extra=()):
    return list(EXCLUDED_ALWAYS) + list(extra)


def exclusion_mask(rects):
    """bytearray W*H: 1 -- піксель виключено з порівняння."""
    m = bytearray(W * H)
    for _name, (x1, y1, x2, y2) in rects:
        for y in range(max(0, y1), min(H - 1, y2) + 1):
            for x in range(max(0, x1), min(W - 1, x2) + 1):
                m[y * W + x] = 1
    return m


# --- довідкове піксельне порівняння ---------------------------------------------------------------------------------------

def compare_screens(shot_words, render_px, colors, mask=None):
    """Піксельне порівняння (ДОВІДКА, не критерій). mask -- виключені ділянки. Повертає: diff (усі розбіжні), counted_diff (розбіжні поза виключеними),
    masked_diff (розбіжні у виключених), n_counted, pct_counted, pct_all, by_item {ключ елемента рендеру: кількість} за порівнюваними."""
    diff, counted, masked = [], [], []
    by_item = {}
    n_counted = 0
    for i, (sw, ri) in enumerate(zip(shot_words, render_px)):
        skip = bool(mask and mask[i])
        if not skip:
            n_counted += 1
        if sw == colors[ri]:
            continue
        diff.append(i)
        if skip:
            masked.append(i)
        else:
            counted.append(i)
            by_item[te.KEYS[ri]] = by_item.get(te.KEYS[ri], 0) + 1
    n = len(render_px)
    return {"diff": diff, "counted_diff": counted, "masked_diff": masked, "n_counted": n_counted,
            "pct_counted": (100.0 * len(counted) / n_counted) if n_counted else 0.0, "pct_all": 100.0 * len(diff) / n, "by_item": by_item}


def _rgb(word):
    return cl.rgb565_to_rgb888(struct.pack(">H", word), width=1, height=1)


def triptych_png(shot_words, render_words_, cmp_, mask=None):
    """PNG «рація | наш рендер | різниця» (масштаб 2). Права частина: затемнений рендер; ЖОВТИМ -- виключені ділянки (не порівнюються); ЧЕРВОНИМ --
    розбіжність поза виключеними (довідково)."""
    red = set(cmp_["counted_diff"])
    gap = 8
    width = (W * 3) * SCALE + 2 * gap
    rows = []
    for y in range(H):
        left, mid, right = bytearray(), bytearray(), bytearray()
        for x in range(W):
            i = y * W + x
            ls = _rgb(shot_words[i])
            ms = _rgb(render_words_[i])
            if i in red:
                rs_ = b"\xff\x00\x00"
            elif mask and mask[i]:
                rs_ = b"\x70\x60\x00"
            else:
                rs_ = bytes(c // 4 for c in ms)
            left += ls * SCALE
            mid += ms * SCALE
            right += rs_ * SCALE
        line = bytes(left) + b"\x80\x80\x80" * gap + bytes(mid) + b"\x80\x80\x80" * gap + bytes(right)
        rows.extend([line] * SCALE)
    return cl.encode_png(width, H * SCALE, b"".join(rows))


def regions_text(idx, limit=3):
    """Охоплювальні прямокутники змін, згруповані за рядками екрана (грубо): «x1..x2, y1..y2»."""
    if not idx:
        return "нема"
    ys = sorted({i // W for i in idx})
    groups = []
    start = prev = ys[0]
    for y in ys[1:]:
        if y > prev + 2:
            groups.append((start, prev))
            start = y
        prev = y
    groups.append((start, prev))
    parts = []
    for y1, y2 in groups[:limit]:
        xs = [i % W for i in idx if y1 <= i // W <= y2]
        parts.append("x %d..%d, y %d..%d" % (min(xs), max(xs), y1, y2))
    return "; ".join(parts) + ("; і ще %d зон" % (len(groups) - limit) if len(groups) > limit else "")


def layout_score(shot_words, render_px, mask=None):
    """Скільки пікселів поза маскою «перефарбовують» рендер у знімок: кожному елементу теми в рендері ставиться найчастіший колір знімка в його пікселях.
    Міра не залежить від того, ЯКІ саме кольори на знімку, тож екран впізнається навіть тоді, коли тема на рації інша (інакше хибний колір ховав би
    екран від перевірки зон)."""
    by_item = {}
    for i, (sw, ri) in enumerate(zip(shot_words, render_px)):
        if mask and mask[i]:
            continue
        c = by_item.get(ri)
        if c is None:
            c = by_item[ri] = collections.Counter()
        c[sw] += 1
    return sum(c.most_common(1)[0][1] for c in by_item.values())


def best_match(shot_words, theme_sets, screens=None, state=None, mask=None):
    """Для кожного екрана передпоказу (і кожної теми для довідкової різниці) -- список (pct_counted, pct_all, ключ, ім'я теми, cmp, слова рендеру, Display,
    layout_score) від найкращого. Екран впізнається за layout_score (форма, незалежна від кольорів), різниця пікселів лише розв'язує нічиї. Для екрана каналу
    з реальним `state` пробуються два варіанти заряду (99 % і 100 %: від нього залежить зсув тексту шапки)."""
    sv = _sv()
    out = []
    for key, _title in (screens or te.preview_screens()):
        variants = [sv.render(key)]
        if key == "channel" and state is not None:
            variants = [sv.render(key, dict(state, battery_pct=p)) for p in (99, 100)]
        for disp in variants:
            score = layout_score(shot_words, disp.px, mask)
            for tname, colors in theme_sets:
                c = compare_screens(shot_words, disp.px, colors, mask)
                out.append((c["pct_counted"], c["pct_all"], key, tname, c, render_words(disp, colors), disp, score))
    out.sort(key=lambda t: (-t[7], len(t[4]["counted_diff"]), t[1]))
    return out


# --- палітра (E2.1) ---------------------------------------------------------------------------------------------------------

def palette_report(shot_words, theme_sets):
    """Для кожної теми -- які кольори знімка в її палітрі НЕ входять. Повертає [(кількість чужих пікселів, ім'я теми, colors, {слово: кількість})]
    від найкращої (за порядком наведення при рівності)."""
    hist = collections.Counter(shot_words)
    out = []
    for tname, colors in theme_sets:
        pal = set(colors)
        foreign = {w: n for w, n in hist.items() if w not in pal}
        out.append((sum(foreign.values()), tname, colors, foreign))
    out.sort(key=lambda t: t[0])
    return out


def colour_box(shot_words, word):
    """Охоплювальний прямокутник пікселів кольору `word` на знімку."""
    idx = [i for i, w in enumerate(shot_words) if w == word]
    xs = [i % W for i in idx]
    ys = [i // W for i in idx]
    return "x %d..%d, y %d..%d" % (min(xs), max(xs), min(ys), max(ys))


# --- зони (E2.2): координати з розкладки screen_views.LAYOUT -------------------------------------------------------------------------

def channel_zones(digital=True):
    """Зони екрана каналу: [(назва, (x1,y1,x2,y2), ключ тла, (ключі кольору тексту))]. Тло зони має домінувати, а решта пікселів -- бути кольором тексту,
    який тема призначає саме цій зоні. Координати -- з LAYOUT (ті самі, якими малює передпоказ)."""
    L = _sv().L
    top = L["DISPLAY_Y_POS_CONTACT"]
    name_y = _sv().channel_first_line_y()
    zones = [("шапка (режим, TS, потужність, CC, заряд)", (0, 0, W - 1, L["DISPLAY_Y_POS_BAR"] - 1), "BG_HEADER_TEXT", ("FG_HEADER_TEXT",))]
    if digital:
        zones.append(("контакт", (0, top, W - 1, top + L["MENU_ENTRY_HEIGHT"] - 1), "BG", ("FG_CHANNEL_CONTACT", "FG_CHANNEL_CONTACT_INFO")))
    zones.append(("назва каналу", (0, name_y, W - 1, name_y + L["MENU_ENTRY_HEIGHT"] - 1), "BG", ("FG_CHANNEL_NAME", "FG_CHANNEL_CONTACT_INFO")))
    zones.append(("нижній рядок (зона й номер каналу)", (0, L["DISPLAY_Y_POS_ZONE"], W - 1, L["DISPLAY_Y_POS_ZONE"] + 7), "BG", ("FG_ZONE_NAME",)))
    zones.append(("верхня рамка S-метра", (0, L["SMETER_BLOCK_Y"], W - 1, L["SMETER_BLOCK_Y"]), "FG_DECORATION", ()))
    return zones


def zone_check(shot_words, colors, rect, bg_key, ink_keys):
    """Повертає (ok, що_отримано, що_очікувалось). ok, якщо (1) у зоні домінує колір, який тема призначає тлу зони, і (2) серед решти пікселів найчастіший
    колір -- один із призначених тексту зони (порожня зона без тексту -- теж гаразд)."""
    x1, y1, x2, y2 = rect
    hist = collections.Counter(shot_words[y * W + x] for y in range(y1, y2 + 1) for x in range(x1, x2 + 1))
    bg = colors[te.INDEX[bg_key]]
    ink = {}
    for k in ink_keys:
        ink.setdefault(colors[te.INDEX[k]], []).append(k)
    exp = "домінує %s %s" % (bg_key, te.to_hex(bg))
    if ink:
        exp += "; текст -- %s" % " або ".join("%s %s" % ("/".join(ks), te.to_hex(w)) for w, ks in ink.items())
    dom, dom_n = hist.most_common(1)[0]
    if dom != bg:
        return False, "домінує %s (%d з %d пікселів)" % (te.to_hex(dom), dom_n, sum(hist.values())), exp
    rest = [(w, n) for w, n in hist.most_common() if w != bg]
    if rest and ink and rest[0][0] not in ink:
        return False, "текст намальовано кольором %s (%d пікселів), а тема призначає %s" % (te.to_hex(rest[0][0]), rest[0][1], " або ".join(sorted(k for ks in ink.values() for k in ks))), exp
    got = "тло %s" % te.to_hex(bg) + ("; текст %s" % te.to_hex(rest[0][0]) if rest else "; тексту нема")
    return True, got, exp


# --- S-метр: рівень сигналу з самого знімка, далі блок порівнюється ТОЧНО ----------------------------------------------------------------

SMETER_TEXT_BOX = (132, 57, 159, 64)


def smeter_level(shot_words, colors):
    """Рівень сигналу в дБм, який показує підпис S-метра на знімку (текст FG_DEFAULT у правому куті блока), або None. Підпис порівнюється з підписами,
    які малює передпоказ для кожного рівня; якщо FG_DEFAULT збігається з тлом теми, підпис невидимий і рівня не визначити."""
    sv = _sv()
    import screen_sim as sim
    fg_i = te.INDEX["FG_DEFAULT"]
    if colors[fg_i] == colors[te.INDEX["BG"]]:
        return None
    x1, y1, x2, y2 = SMETER_TEXT_BOX
    cells = [(x, y) for y in range(y1, y2 + 1) for x in range(x1, x2 + 1)]
    shot_mask = tuple(shot_words[y * W + x] == colors[fg_i] for x, y in cells)
    if not any(shot_mask):
        return None
    for dbm in range(-150, -29):
        d = sim.Display()
        sv.draw_smeter_block(d, dbm)
        if tuple(d.px[y * W + x] == fg_i for x, y in cells) == shot_mask:
            return dbm
    return None


def smeter_check(shot_words, colors):
    """Блок S-метра (y 41..63). Якщо рівень визначено з підпису -- блок має збігатися з намальованим передпоказом ТОЧНО, окремо за частинами:
    смуга до S9, смуга вище S9, решта (рамка, поділки, цифри шкали). Повертає (dbm|None, [(назва, ok, отримано, очікувалось)])."""
    sv = _sv()
    import screen_sim as sim
    L = sv.L
    dbm = smeter_level(shot_words, colors)
    y1, y2 = L["SMETER_BLOCK_Y"], L["SMETER_BLOCK_Y"] + L["SMETER_BLOCK_H"] - 1
    if dbm is None:
        # рівень невідомий: смуга (y 43..50) може містити лише тло та два кольори смуги
        allowed = {colors[te.INDEX[k]] for k in ("BG", "FG_RSSI_BAR", "FG_RSSI_BAR_S9P")}
        ys = range(L["SMETER_BAR_Y"], L["SMETER_BAR_Y"] + L["SMETER_BAR_H"])
        xs = range(L["SMETER_BAR_X"], L["SMETER_BAR_X"] + L["SMETER_BAR_WIDTH"])
        bad = collections.Counter(shot_words[y * W + x] for y in ys for x in xs if shot_words[y * W + x] not in allowed)
        got = "лише тло й кольори смуги" if not bad else "чужі кольори в смузі: " + ", ".join("%s ×%d" % (te.to_hex(w), n) for w, n in bad.most_common(3))
        return None, [("смуга S-метра: кольори (рівень за підписом не визначено)", not bad, got, "тло, FG_RSSI_BAR, FG_RSSI_BAR_S9P")]
    d = sim.Display()
    sv.draw_smeter_block(d, dbm)
    bar_w = max(0, min(sv.smeter_pixel_pos(dbm), L["SMETER_BAR_WIDTH"]))
    s9 = L["SMETER_S9_POS"]
    bx, by, bh = L["SMETER_BAR_X"], L["SMETER_BAR_Y"], L["SMETER_BAR_H"]

    def part(i, x, y):
        if by <= y < by + bh and bx <= x < bx + L["SMETER_BAR_WIDTH"]:
            if x < bx + s9:
                return "below"
            return "above"
        return "rest"
    bad = {"below": [], "above": [], "rest": []}
    tot = {"below": 0, "above": 0, "rest": 0}
    for y in range(y1, y2 + 1):
        for x in range(W):
            i = y * W + x
            p = part(i, x, y)
            tot[p] += 1
            if shot_words[i] != colors[d.px[i]]:
                bad[p].append(i)
    out = []
    names = (("below", "смуга S-метра до S9"), ("above", "смуга S-метра вище S9"), ("rest", "рамка, поділки, цифри S-метра"))
    for p, label in names:
        if p == "above" and bar_w <= s9:
            continue
        if p == "below" and bar_w == 0:
            continue
        exp_item = {"below": "FG_RSSI_BAR", "above": "FG_RSSI_BAR_S9P", "rest": "FG_DECORATION/FG_DEFAULT/ТЛО"}[p]
        if bad[p]:
            wrong = collections.Counter(shot_words[i] for i in bad[p])
            got = "%d з %d пікселів не за темою (найчастіше %s)" % (len(bad[p]), tot[p], te.to_hex(wrong.most_common(1)[0][0]))
        else:
            got = "збігається (%d пікселів)" % tot[p]
        out.append(("%s (за підписом %d дБм)" % (label, dbm), not bad[p], got, "колір %s" % exp_item if p != "rest" else "як у темі"))
    return dbm, out


# --- сценарій -----------------------------------------------------------------------------------------------------------------

def _theme_sets(ctx):
    sets, sources = [], []
    for daytime in ("day", "night"):
        state, colors = te.read_theme(ctx.link.ser, daytime)
        src = "прочитана з рації"
        if colors is None:
            colors = te.stock_colors(daytime)
            src = "стандартна (в рації власної теми нема)"
        sets.append((te.DAYTIME_NAMES[daytime].lower(), colors))
        sources.append(src)
    return sets, sources


def s3(ctx, res):
    sv = _sv()
    raw, stable, reads = capture_stable(ctx.link, log=ctx.log)
    res.check("знімок екрана рації прочитано", "%d Б" % (W * H * 2), "%d Б" % len(raw), len(raw) >= W * H * 2)
    res.check("кадр стабільний (два читання поспіль збіглися)", "стабільний", ("стабільний, потрібно читань: %d" % reads) if stable else
              "екран змінювався під час усіх %d читань" % reads, stable, "" if stable else "Далі кадр не аналізується: рваний кадр дав би хибні провали. Повторіть, коли екран не змінюється.")
    if not stable:
        return
    shot = screen_words(raw)
    sets, sources = _theme_sets(ctx)

    # 1) палітра -- головний критерій
    pal = palette_report(shot, sets)
    n_foreign, tname, colors, foreign = pal[0]
    src = sources[[s[0] for s in sets].index(tname)]
    n_colors = len(set(shot))
    if foreign:
        top = sorted(foreign.items(), key=lambda kv: -kv[1])
        got = "%d кольорів знімка не належать темі «%s» (найближча): " % (len(foreign), tname) + "; ".join(
            "%s ×%d (%s)" % (te.to_hex(w), n, colour_box(shot, w)) for w, n in top[:3])
    else:
        got = "усі %d кольорів знімка -- з палітри теми «%s» (%s)" % (n_colors, tname, src)
    res.check("палітра: усі кольори знімка належать палітрі теми з рації", "жодного чужого кольору", got, not foreign,
              "Чужий колір -- справжній дефект: або тема в рації не та, що вважає майстер, або екран малює колір поза темою. Якщо ви крутили гучність чи тримали клавішу, повторіть."
              if foreign else "")

    # 2) поточна зона/канал, рендер із реальними даними
    cp = ctx.codeplug()
    sel = read_current_selection(cp)
    if not sel["known"]:
        res.info("поточний канал рації", "не визначено", sel["why"])
        chooser = getattr(ctx, "choose", None)
        if chooser:
            choices = selection_choices(cp)
            if choices:
                k = chooser("Самоперевірка S3: який канал зараз на екрані рації?",
                            "Поточний канал не вдалося прочитати з рації (%s). Оберіть зі списку зону й канал, які ЗАРАЗ показані на екрані. "
                            "Перший канал підставлено не буде." % sel["why"], [lab for lab, _s in choices])
                if k is not None and 0 <= k < len(choices):
                    sel = choices[k][1]
    state = extra = None
    if sel["known"]:
        state, extra, _notes = real_state(cp, sel)
        res.info("поточний канал рації", "зона «%s», №%d в зоні, канал %d «%s»" % (sel["zone_name"], sel["pos_in_zone"], sel["channel_no"], state["channel"]),
                 "джерело: %s. Рація записує поточний вибір із затримкою (гіпотеза): якщо щойно перемикали канал, дані можуть бути застарілі." % sel["source"])
    else:
        res.info("піксельне порівняння з рендером", "не робиться",
                 "канал не визначено й не обрано вручну; рендер із прикладними даними лише для ілюстрації, відсоток не рахується")
    rects = exclusion_rects(extra or ())
    mask = exclusion_mask(rects)
    ranked = best_match(shot, sets, state=state, mask=mask)
    disp = ranked[0][6]
    key = ranked[0][2]
    # довідкова різниця -- з темою, чия палітра найкраще підійшла знімку (а не з тією, що дала найменше розбіжних пікселів)
    pc, pa, key, rname, cmp_, rendered, disp, _score = next(r for r in ranked if r[6] is disp and r[3] == tname)
    others = []
    for r in ranked:
        if r[2] != key and r[2] not in [o[0] for o in others] and r[3] == tname:
            others.append((r[2], r[7]))
    res.info("найближчий екран передпоказу", "«%s», %s тема" % (sv.SCREEN_TITLES[key], rname),
             "екран впізнано за формою, а не за кольорами. Інші кандидати (збіг форми, пікселів): " + "; ".join("%s -- %d" % o for o in others[:3]))

    # 3) зони -- другий головний критерій
    if key == "channel":
        digital = (state or {}).get("mode", "dmr") != "fm"
        for zname, rect, bg_key, ink_keys in channel_zones(digital):
            ok, got_z, exp_z = zone_check(shot, colors, rect, bg_key, ink_keys)
            res.check("зона «%s»: колір за темою" % zname, exp_z, got_z, ok)
        dbm, parts = smeter_check(shot, colors)
        if dbm is not None:
            res.info("рівень сигналу (з підпису S-метра)", "%d дБм" % dbm)
        for label, ok, got_z, exp_z in parts:
            res.check(label, exp_z, got_z, ok)
    else:
        res.info("зони екрана", "не перевірялись", "для екрана «%s» зони не визначено; діє лише перевірка палітри. Для S3 залиште на рації екран каналу (не VFO, не меню)." % sv.SCREEN_TITLES[key])

    # 4) піксельна різниця -- лише довідка
    if sel["known"]:
        res.info("довідково: пікселів, що розходяться з рендером (поза виключеними)", "%.3f %% (%d з %d порівнюваних)" % (pc, len(cmp_["counted_diff"]), cmp_["n_counted"]),
                 "НЕ критерій: порога нема. ділянки: " + regions_text(cmp_["counted_diff"]))
        if cmp_["by_item"]:
            top = sorted(cmp_["by_item"].items(), key=lambda kv: -kv[1])[:5]
            res.info("довідково: розбіжності за елементами теми (за рендером)", "; ".join("%s -- %d" % kv for kv in top))
    res.info("виключено з порівняння (стан рації, якого немає в кодплазі)", "; ".join("%s -- x %d..%d, y %d..%d" % (n, r[0], r[2], r[1], r[3]) for n, r in rects),
             "у цих ділянках палітра перевіряється, а піксельне порівняння -- ні")
    path = cl.unique_path(ctx.mkdir(), "selfcheck_screen_%s.png" % ctx.stamp)
    with open(path, "wb") as f:
        f.write(triptych_png(shot, rendered, cmp_, mask))
    res.artifacts.append(("знімок | рендер | різниця (жовтим -- виключено з порівняння, червоним -- розбіжність поза виключеними, довідково)", path))
    res.notes.append("S3 вирішують палітра й зони (див. кроки вище). Піксельна різниця -- довідка: після кількох прогонів на живій рації з неї буде виведено поріг "
                     "(у R39 його навмисно нема: виміряних даних ще немає).")


# =============================================================================================================================
#  S4: сценарії запису
# =============================================================================================================================

def s4_1(ctx, res):
    daytime = "day"
    name = te.DAYTIME_NAMES[daytime].lower()
    link = ctx.link
    state, colors0 = te.read_theme(link.ser, daytime)
    if state != te.ST_OK:
        res.skip_reason = ("блока %s теми в рації нема або він нестандартний (%s): запис створив би блок, який не можна прибрати без втрати місця. "
                           "Збережіть тему в розділі «Теми» і повторіть." % (name, te.STATE_TEXT[state]))
        return
    region0 = cr.read_radio_region(link)
    idx = te.INDEX["BG_MENU_NAME"]
    colors1 = list(colors0)
    colors1[idx] = colors0[idx] ^ 0x0020
    res.check("тестовий колір відрізняється від поточного", "інший", "%s -> %s" % (te.to_hex(colors0[idx]), te.to_hex(colors1[idx])), colors1[idx] != colors0[idx])
    with guarded_customdata_writes(ctx, "S4.1"):
        try:
            msg = te.write_theme(link.ser, daytime, colors1)
        except (RuntimeError, cl.CpsError, fg.GuardError) as e:
            res.check("запис теми", "записано й звірено", str(e), False)
            _theme_rollback(ctx, res, daytime, region0)
            return
        res.check("запис теми і звірка читанням (te.write_theme)", "записано й звірено", msg, "Звірка читанням: OK" in msg)
        _, got = te.read_theme(link.ser, daytime)
        res.check("перечитана тема має змінений колір", te.to_hex(colors1[idx]), te.to_hex(got[idx]) if got else "нема", bool(got) and got[idx] == colors1[idx])
        res.check("решта 31 кольору не змінилась", "змінився лише один елемент", "змінилось елементів: %d" % sum(1 for a, b in zip(got or [], colors0) if a != b),
                  bool(got) and sum(1 for a, b in zip(got, colors0) if a != b) == 1)
        region1 = cr.read_radio_region(link)
        res.check("область custom-data: змінено лише 64 байти блока теми", "не більше 64 байтів", "змінено %d байтів (%s)" % (
            sum(b - a for a, b in _diff_ranges(region0, region1)), _ranges_text(_diff_ranges(region0, region1))),
            sum(b - a for a, b in _diff_ranges(region0, region1)) <= te.BLOCK_LEN)
        # --- повернути ---
        try:
            te.write_theme(link.ser, daytime, colors0)
        except (RuntimeError, cl.CpsError, fg.GuardError) as e:
            res.check("повернення початкової теми", "повернуто", str(e), False)
            _theme_rollback(ctx, res, daytime, region0, already_failed=True)
            return
    region2 = cr.read_radio_region(link)
    res.check("повернення: область custom-data ПОБАЙТОВО та сама, що до сценарію", _short(_sha(region0)), _short(_sha(region2)), region0 == region2,
              "" if region0 == region2 else "різниця: " + _ranges_text(_diff_ranges(region0, region2)))
    if region0 != region2:
        _loud_restore_failure(ctx, res, "тема", "область custom-data відрізняється від початкової", ctx.snapshot["path"] if ctx.snapshot else None)


def _theme_rollback(ctx, res, daytime, region0, already_failed=False):
    """Невдача посеред S4.1: пробуємо записати початкову тему ще раз і звіряємо всю область; не вийшло -- голосно."""
    try:
        orig_block = _block_of(region0, te.TYPE_OF[daytime])
        if orig_block is None:
            raise RuntimeError("у початковій області блока теми нема")
        with guarded_customdata_writes(ctx, "S4.1 аварійне повернення"):
            ok, msg = cd.write_block(ctx.link.ser, te.TYPE_OF[daytime], orig_block)
        if not ok:
            raise RuntimeError(msg)
        now = cr.read_radio_region(ctx.link)
        same = now == region0
        res.check("аварійне повернення теми", "область така сама, як була", "та сама" if same else "ІНША: " + _ranges_text(_diff_ranges(region0, now)), same)
        if not same:
            raise RuntimeError("область після повернення відрізняється")
    except (RuntimeError, cl.CpsError, fg.GuardError) as e:
        _loud_restore_failure(ctx, res, "тема", str(e), ctx.snapshot["path"] if ctx.snapshot else None)


def _block_of(region, dtype):
    sc = ccmp.scan_region(region)
    for e in sc.live:
        if e.type == dtype:
            return e.payload
    return None


def s4_2(ctx, res):
    vfo = 0

    def build(img):
        dp = "."
        cur_rec = ve.vfo_rec(img, vfo)
        cur_rx = cv.freq_bcd_le(cur_rec[cc.O_RX:cc.O_RX + 4])
        want = TEST_FREQ[1] if cur_rx == int(round(float(TEST_FREQ[0]) * 100000)) else TEST_FREQ[0]
        ctx_state = {"want": int(round(float(want) * 100000))}
        res.info("VFO A: було", "RX %s" % (("%d.%05d МГц" % divmod(cur_rx, 100000)) if cur_rx else "невалідний запис"), "записую RX = TX = %s МГц" % want)
        base = img
        try:
            r = ve.vfo_edit(base, vfo, {"Rx Frequency": want, "Tx Frequency": want}, dp)
        except ced.CodeplugEditError:
            base = ve.vfo_init(img, vfo, dp).image          # порожній VFO -> типовий, далі знову наш запис
            r = ve.vfo_edit(base, vfo, {"Rx Frequency": want, "Tx Frequency": want}, dp)
            res.info("VFO A порожній", "спершу заповнено типовими значеннями (як це зробила б прошивка)")
        build.want = ctx_state["want"]
        r.changed.append(("VFO", "VFO A: частоти %s МГц (самоперевірка)" % want))
        return r

    def verify(img, rs_):
        rec = ve.vfo_rec(img, vfo)
        rx, tx = cv.freq_bcd_le(rec[cc.O_RX:cc.O_RX + 4]), cv.freq_bcd_le(rec[cc.O_TX:cc.O_TX + 4])
        rs_.check("VFO A після запису: RX і TX = записані", "%d / %d (×10 Гц)" % (build.want, build.want), "%s / %s" % (rx, tx), rx == build.want and tx == build.want)

    _roundtrip(ctx, res, "S4.2", build, verify, "VFO A: тимчасове відоме значення, далі повертається.", expect_sectors=3)


def _free_channel_number(img):
    per = cl.CP_CHANNELS_PER_BANK
    top = cl.CP_CHANNELS_BANKS * per
    for n in range(per + 1, top + 1):       # спершу флеш-банки: EEPROM-банк 0 стоїть поряд із ділянками, що рація міняє сама
        if not img.channel_in_use(n):
            return n
    for n in range(1, per + 1):
        if not img.channel_in_use(n):
            return n
    return None


def s4_3(ctx, res):
    state = {}

    def build(img):
        n = _free_channel_number(img)
        if n is None:
            raise cl.CpsError("вільного номера каналу нема")
        raw, enc = cc.encode_new_name(CHANNEL_NAME_TEST)
        out = cc.Image(img.eeprom, img.flash, img.base)
        rec = cc.new_channel_template(False)
        rec[cc.O_NAME:cc.O_NAME + 16] = cc.pad16(raw)
        cctx = cc.make_ctx_for_export(out, ".")
        for col in ("Rx Frequency", "Tx Frequency"):
            cc.CH_COLUMN_BY_NAME[col]["enc"](rec, "145.5", cctx)
        out.set_channel_rec(n, bytes(rec))
        out.set_channel_in_use(n, True)
        r = ce.apply_ops(out, [{"op": "add", "name": CONTACT_NAME_TEST, "id": CONTACT_ID_TEST, "type": 0}])
        r.added.append(("Канали", "№%d %s (самоперевірка)" % (n, CHANNEL_NAME_TEST)))
        state.update(n=n, enc=enc, contact_slots=set(dict(img.contacts())))
        res.info("номер вільного каналу / кодування назви «%s»" % CHANNEL_NAME_TEST, "№%d / %s" % (n, enc))
        return r

    def verify(img, rs_):
        n = state["n"]
        rec = img.channel_rec(n) if img.channel_in_use(n) else None
        rs_.check("канал №%d у роботі" % n, "так", "так" if rec is not None else "ні", rec is not None)
        if rec is not None:
            text = cv.decode_name_ex(rec[:16])[0]
            rs_.check("назва каналу читається «%s»" % CHANNEL_NAME_TEST, CHANNEL_NAME_TEST, text, text == CHANNEL_NAME_TEST,
                      "байти %s (%s)" % (bytes(rec[:16]).hex(" "), state["enc"]))
        new = [(s_, r_) for s_, r_ in img.contacts() if s_ not in state["contact_slots"]]
        rs_.check("з'явився рівно один новий контакт", "1", str(len(new)), len(new) == 1)
        if new:
            slot, crec = new[0]
            text = cv.decode_name_ex(crec[:16])[0]
            rs_.check("назва контакту «%s»: «я» на місці" % CONTACT_NAME_TEST, CONTACT_NAME_TEST, text, text == CONTACT_NAME_TEST, "байти %s" % bytes(crec[:16]).hex(" "))
            nb = cv.name_bytes(crec[:16])
            tail_ok = nb.endswith(b"\xff") and bytes(crec[len(nb):len(nb) + 1]) == b"\x00"
            rs_.check("кінцева «я» (0xFF) має хвіст 0x00 (R36)", "…ff 00", bytes(crec[max(0, len(nb) - 1):len(nb) + 2]).hex(" "), tail_ok)
            rs_.check("ID і тип контакту", "%d, тип 0" % CONTACT_ID_TEST, "%s, тип %d" % (cv.bcd_to_int(crec[16:20]), crec[20]),
                      cv.bcd_to_int(crec[16:20]) == CONTACT_ID_TEST and crec[20] == 0)

    _roundtrip(ctx, res, "S4.3", build, verify, "Канал «Зоря» і контакт «Надія»: тимчасово, далі видаляються (початковий стан повертається).", expect_sectors=6)


def _block_to_mutate(region):
    """Живий блок, який безпечно змінити на мить: не ключ AES, не тема (її перевіряє S4.1); бажано з сусідами з обох боків. Повертає Entry або None."""
    sc = ccmp.scan_region(region)
    live = sc.live
    cand = [(i, e) for i, e in enumerate(live) if e.type not in (cr.TYPE_AES_KEYS,) and e.length >= 1]
    if not cand:
        return None
    mid = [(i, e) for i, e in cand if 0 < i < len(live) - 1 and e.type not in (4, 5)]
    pick = mid or [(i, e) for i, e in cand if e.type not in (4, 5)] or cand
    return min(pick, key=lambda t: t[1].length)[1]


def s4_4(ctx, res):
    link = ctx.link
    region0 = cr.read_radio_region(link)
    scan0 = ccmp.scan_region(region0)
    if not scan0.magic_ok or scan0.problems:
        res.skip_reason = "область custom-data в рації відсутня або пошкоджена (%s): блока, який можна безпечно змінити й повернути, нема" % "; ".join(scan0.problems)
        return
    ent = _block_to_mutate(region0)
    if ent is None:
        res.skip_reason = "у рації нема живого блока, який можна змінити й повернути, не витрачаючи місця в області (новий блок не можна прибрати без втрати місця)"
        return
    res.info("обраний блок", "%s (тип %d), @%d, %d Б" % (ent.title, ent.type, ent.offset, ent.length),
             "сусідів: до -- %s, після -- %s" % (any(e.offset < ent.offset for e in scan0.entries), any(e.offset > ent.offset for e in scan0.entries)))
    pattern = bytes((b ^ 0xA5) for b in ent.payload)
    if pattern == ent.payload:
        pattern = bytes((b + 1) & 0xFF for b in ent.payload)
    lo, hi = ent.offset + ccmp.BLOCK_HDR, ent.offset + ccmp.BLOCK_HDR + ent.length
    with guarded_customdata_writes(ctx, "S4.4"):
        ok, msg = cd.write_block(link.ser, ent.type, pattern)
        res.check("запис відомого значення в блок", "записано", msg, ok)
        region1 = cr.read_radio_region(link)
        if not ok or region1 == region0:
            # нічого не змінилось або запис відхилено -- повертати нічого, але звірити
            res.check("область після запису", "змінилась лише в межах блока", "не змінилась", ok and region1 != region0)
        else:
            res.check("блок містить записане", _short(_sha(pattern)), _short(_sha(region1[lo:hi])), region1[lo:hi] == pattern)
            outside_ok = region1[:lo] == region0[:lo] and region1[hi:] == region0[hi:]
            res.check("сусідні блоки та решта області побайтово не змінились (гіпотеза R30)", "лише %d Б блока" % ent.length,
                      "змінено байтів поза блоком: %d" % (sum(b - a for a, b in _diff_ranges(region0[:lo], region1[:lo])) + sum(b - a for a, b in _diff_ranges(region0[hi:], region1[hi:]))),
                      outside_ok)
        # --- повернути ---
        ok2, msg2 = cd.write_block(link.ser, ent.type, ent.payload)
        res.check("повернення початкового вмісту блока", "записано", msg2, ok2)
    region2 = cr.read_radio_region(link)
    same = region2 == region0
    res.check("повернення: область ПОБАЙТОВО та сама, що до сценарію", _short(_sha(region0)), _short(_sha(region2)), same,
              "" if same else "різниця: " + _ranges_text(_diff_ranges(region0, region2)))
    if not same:
        _loud_restore_failure(ctx, res, "блок", "область custom-data відрізняється від початкової", ctx.snapshot["path"] if ctx.snapshot else None)


# =============================================================================================================================
#  Реєстр сценаріїв і ручні кроки (S5)
# =============================================================================================================================

SCENARIOS = [
    Scenario("S2.1", "Розділи кодплага: позивний, DMR ID, кількості, назви", RISK_READ, s2_1),
    Scenario("S2.2", "Теми: з рації, збіг зі зашитими палітрами, .gtm і назад", RISK_READ, s2_2, closes=("2.3", "2.5")),
    Scenario("S2.3", "Бекапи: звичайний, повний, без ключів; SHA-256 за маніфестом", RISK_READ, s2_3, closes=("2.6", "2.7", "2.8")),
    Scenario("S2.4", "Область custom-data: блоки, зайнято / вільно / вилучено", RISK_READ, s2_4, closes=("2.14",)),
    Scenario("S2.5", "Ключі AES: які слоти зайняті (лише номери)", RISK_READ, s2_5),
    Scenario("S2.6", "База позивних: заголовок, формат, кількість, довжина запису", RISK_READ, s2_6, closes=("2.9",)),
    Scenario("S2.7", "Голосові підказки: заголовок, версія, скільки фраз", RISK_READ, s2_7),
    Scenario("S2.8", "Назви з малою «я»: як закодовані (хвіст 0xFF чи 0x00)", RISK_READ, s2_8),
    Scenario("S3", "Знімок екрана: палітра й зони за темою", RISK_READ, s3, closes=("2.10",)),
    Scenario("S4.1", "Тема: змінити один колір, перевірити, повернути", RISK_WRITE, s4_1,
             writes=("custom-data: блок денної теми (64 байти, один колір змінюється на мить) -> повертається", "перелік змін перевіряється: решта 31 колір і решта області не змінюються")),
    Scenario("S4.2", "VFO A: записати відоме значення, перевірити, повернути", RISK_WRITE, s4_2,
             writes=("кодплаг (EEPROM): запис VFO A (частоти RX/TX) -> повертається", "кожен запис -- через страхову копію й звірку SHA-256")),
    Scenario("S4.3", "Канал «Зоря» і контакт «Надія»: записати, перевірити «я», видалити", RISK_WRITE, s4_3,
             writes=("кодплаг: додається канал «Зоря» у вільний номер і контакт «Надія» (ID %d) -> обидва видаляються" % CONTACT_ID_TEST,
                     "після видалення кодплаг має бути побайтово таким, як був")),
    Scenario("S4.4", "Область custom-data: записати блок, перевірити сусідів, повернути", RISK_WRITE, s4_4,
             writes=("custom-data: вміст одного живого блока (не ключі AES) на мить замінюється відомим -> повертається", "сусідні блоки мають лишитись побайтово тими самими")),
]
SCENARIO_BY_ID = {s.sid: s for s in SCENARIOS}

# S5. Що лишається людині. (номер чек-листа, текст, яким сценарієм перевіряється ЧАСТИНА з машинного боку)
MANUAL = [
    ("1.1", "Канал з назвою від нашого CPS (cp1251) читається в «Деталях каналу» на рації", None),
    ("1.2", "Канал з назвою від стокового TYT CPS (GBK-пари) -- те саме (важливіший випадок)", "S2.8"),
    ("1.3", "Відредагувати назву кнопками рації -> зберегти -> перевірити в меню і на головному екрані", None),
    ("1.5", "Меню тем -> SK1 + зелена: побачити вбудовану українську палітру", None),
    ("1.6", "DTMF-контакт: набрати й ПОСЛУХАТИ, чи звучить саме набраний код", None),
    ("1.7", "Контакт «Надія» змінити кнопками рації -> зберегти -> «я» на місці (S2.8 прочитає результат)", "S2.8"),
    ("2.1", "Слот APRS: символ лише картинкою, числових полів нема", None),
    ("2.2", "«Загальні налаштування» збігаються з меню рації", None),
    ("2.4", "Завантажити theme_night.gtm у стоковий CPS і порівняти кольори", "S2.2"),
    ("2.5", "Відкрити збережений .gtm стоковим CPS -- чи читається", "S2.2"),
    ("2.11", "ContactLists: завантажити, фільтр 255, повний список у таблиці", None),
    ("2.12", "«Перевірити джерело» для обох адрес RadioID -- яка жива", None),
    ("2.13", "Celestrak: «Перевірити джерело» -- чи адреса робоча", None),
    ("3.1", "VFO: після ПЕРЕЗАПУСКУ рація показує новий VFO (S4.2 перевіряє запис і повернення, не перезапуск)", "S4.2"),
    ("3.2", "Змінити колір тла -> застосувати -> ВИМКНУТИ й УВІМКНУТИ рацію -> видно зміну (S4.1 перевіряє лише запис)", "S4.1"),
    ("3.3", "«Скинути до стокової»; день/ніч беруть обидві теми", None),
    ("3.6", "Тривалості DTMF -> перезапустити рацію", None),
    ("3.7", "Пароль: поставити PIN, перезапустити, ввести, зняти", None),
    ("3.9", "Контакти в розділі: додати, змінити, видалити, записати (S4.3 перевіряє додавання й видалення)", "S4.3"),
    ("3.10", "Канал «Зоря» нашим CPS -> СТОКОВЕ TYT CPS бачить назву", "S4.3"),
    ("3.11", "Тема + SMS -> бекап -> змінити -> відновити з прапорцем -> ВИМКНУТИ кнопкою й увімкнути (S4.4 перевіряє сусідні блоки)", "S4.4"),
    ("3.13", "Стерти слот ключа -> «Відновити лише ключі AES…» -> канал працює (S4.5: машина ключів НЕ чіпає)", None),
    ("3.17", "Супутники: TLE з Celestrak, 3 супутники -> екран супутників на рації", None),
    ("3.18", "Картинка: PNG -> при вмиканні на рації (полярність біта)", None),
    ("3.19", "«Прибрати картинку» -> текстова заставка", None),
    ("3.20", "Мелодія: записати -> чути; «без заставки і мелодії»; «Повернути»", None),
    ("3.21", "Підказки: зберегти у файл -> стерти -> записати з файла -> працюють на слух", None),
    ("3.22", "Залити картинку -> прибрати, тричі -> лічильник вилучених росте -> ущільнити", None),
    ("4.1", "Друга рація: вітальні рядки з кирилицею -> як прийняла (Talker Alias)", None),
    ("4.2", "Друга рація: AES на щоденній українській збірці, обидва напрями, 3 хв, умисне завмирання", None),
    ("4.3", "Друга рація: BG3 / BG4 -- адміністрування і виклик у стокову станцію", None),
    ("5.1", "Усі розділи при вузькому вікні (1024×768): нічого не обрізано", None),
    ("5.2", "Ctrl+C / Ctrl+V у полях при українській розкладці", None),
    ("5.3", "Копіювання рядка з таблиці й тексту з журналу", None),
    ("5.4", "Сплітери тягнуться, положення пам'ятається між запусками", None),
]


# =============================================================================================================================
#  Прогін
# =============================================================================================================================

def order(selected_ids):
    """Сценарії у порядку виконання: спершу читання, потім запис (щоб кеш читання не застарів)."""
    sel = [SCENARIO_BY_ID[i] for i in selected_ids]
    return [s for s in SCENARIOS if s in sel and s.risk == RISK_READ] + [s for s in SCENARIOS if s in sel and s.risk == RISK_WRITE]


def writes_confirmation_text(selected_ids, snapshot_path=None):
    """Текст підтвердження для сценаріїв запису: перелік того, що буде змінено."""
    lines = ["Сценарії ЗАПИСУ змінять рацію на мить і повернуть її як була:", ""]
    for s in order(selected_ids):
        if s.risk == RISK_WRITE:
            lines.append("  %s %s" % (s.sid, s.title))
            lines += ["      - " + w for w in s.writes]
    lines += ["", "Калібрування, ключі AES і база позивних недосяжні для сценаріїв; їхній SHA-256 порівнюється до і після.",
              "Перед кожним записом кодплага робиться страхова копія (вона містить ключі AES -- секрет).",
              "Повний знімок: %s" % (snapshot_path or "НЕ ЗРОБЛЕНО"),
              "Не вимикай рацію і не виймай кабель до кінця прогону. Продовжити?"]
    return "\n".join(lines)


class Report:
    def __init__(self, ctx, results, started, finished, info, invariants=None, selected=()):
        self.ctx, self.results, self.started, self.finished = ctx, results, started, finished
        self.info = info
        self.invariants = invariants
        self.selected = selected
        self.path = None

    @property
    def all_results(self):
        return self.results + ([self.invariants] if self.invariants else [])

    def counts(self):
        c = {PASS: 0, FAIL: 0, ERROR: 0, SKIPPED: 0, INTERRUPTED: 0}
        for r in self.all_results:
            c[r.status] += 1
        return c

    @property
    def ok(self):
        c = self.counts()
        return not (c[FAIL] or c[ERROR] or c[INTERRUPTED]) and not self.ctx.loud


def _cell(x):
    return str(x).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _step_mark(s):
    return "—" if s.ok is None else ("гаразд" if s.ok else "**НЕ ЗБІГЛОСЬ**")


def render_markdown(rep):
    ctx = rep.ctx
    c = rep.counts()
    L = []
    title = "Самоперевірка рації -- %s" % rep.started.strftime("%Y-%m-%d %H:%M")
    L += ["# " + title, ""]
    i = rep.info or {}
    L.append("Рація: тип %s, прошивка %s, зібрана %s." % (i.get("radioType", "?"), i.get("gitRevision", "?"), i.get("buildDateTime", "?")))
    L.append("Тривалість: %.0f с. Сценаріїв: %d (і перевірка інваріантів, якщо були записи)." % ((rep.finished - rep.started).total_seconds(), len(rep.results)))
    if ctx.snapshot:
        L.append("Повний знімок перед прогоном: `%s` (SHA-256 %s). **Файл секретний** (ключі AES): не пересилайте його." % (ctx.snapshot["path"], _short(ctx.snapshot["sha256"])))
    else:
        L.append("Повний знімок: не робився (сценарії запису не запускались).")
    L.append("")
    L.append("**Підсумок: пройдено %d, НЕ пройдено %d, помилок %d, обірвано %d, пропущено %d.**" % (c[PASS], c[FAIL], c[ERROR], c[INTERRUPTED], c[SKIPPED]))
    L.append("")
    if ctx.loud:
        L += ["## УВАГА -- рація могла лишитись зміненою", ""]
        L += ["- **%s**" % _cell(t) for t in ctx.loud]
        L.append("")
    fails = [(r, s) for r in rep.all_results for s in r.failed_steps()]
    errs = [r for r in rep.all_results if r.error]
    if fails or errs:
        L += ["## Що не пройшло", ""]
        for r in errs:
            L.append("- **%s %s** -- ПОМИЛКА: %s" % (r.scenario.sid, r.scenario.title, _cell(r.error)))
        for r, s in fails:
            L.append("- **%s** -- %s: очікувалось «%s», отримано «%s»" % (r.scenario.sid, s.name, _cell(s.expected), _cell(s.got)))
        L.append("")
    L += ["## Зведення", "", "| № | Сценарій | Ризик | Результат | Кроків | Час, с |", "|---|---|---|---|---|---|"]
    for r in rep.all_results:
        sc = r.scenario
        L.append("| %s | %s | %s | %s | %d | %.1f |" % (sc.sid, _cell(sc.title), RISK_TEXT[sc.risk], STATUS_TEXT[r.status] if r.status == PASS else "**%s**" % STATUS_TEXT[r.status],
                                                          len(r.steps), r.seconds))
    L.append("")
    L.append("## Докладно")
    for r in rep.all_results:
        sc = r.scenario
        L += ["", "### %s %s -- %s" % (sc.sid, sc.title, STATUS_TEXT[r.status]), "", "Ризик: %s. Час: %.1f с." % (RISK_TEXT[sc.risk], r.seconds)]
        if r.skip_reason:
            L += ["", "Пропущено: " + r.skip_reason]
        if r.error:
            L += ["", "**ПОМИЛКА:** " + _cell(r.error)]
        if r.steps:
            L += ["", "| Крок | Очікувано | Отримано | Результат | Час, с |", "|---|---|---|---|---|"]
            for s in r.steps:
                L.append("| %s | %s | %s | %s | %.1f |" % (_cell(s.name), _cell(s.expected), _cell(s.got) + ((" -- " + _cell(s.note)) if s.note else ""), _step_mark(s), s.seconds))
        for n in r.notes:
            L += ["", "> " + _cell(n)]
        for label, path in r.artifacts:
            L += ["", "Файл: %s -- `%s`" % (label, path)]
    if ctx.audit:
        L += ["", "## Усі записи, які зробив прогін", ""]
        L += ["- %s: %s" % (t, d) for t, d in ctx.audit]
    L += ["", "## Що лишається людині (S5)", "",
          "Машина не може натиснути кнопку на рації, почути звук і побачити екран при вмиканні. Ці кроки -- руками, номери з `claude/checklist-cc-cg.md`:", ""]
    done = {r.scenario.sid for r in rep.results if r.status == PASS}
    for num, text, by in MANUAL:
        extra = (" (машинна частина: %s %s)" % (by, "пройдена" if by in done else "не пройдена або не запускалась")) if by else ""
        L.append("- [ ] **%s** %s%s" % (num, text, extra))
    L.append("")
    return "\n".join(L)


def save_report(rep, out_dir=None):
    out_dir = out_dir or rep.ctx.out_dir
    os.makedirs(out_dir, exist_ok=True)
    path = cl.unique_path(out_dir, "selfcheck_%s.md" % rep.started.strftime("%Y-%m-%d_%H-%M"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_markdown(rep))
    rep.path = path
    return path


def run(ctx, selected_ids, confirm_writes=None, cancel=None):
    """Пройти вибрані сценарії. confirm_writes(text) -> bool: підтвердження для сценаріїв запису (без згоди вони пропускаються).
    Нема знімка, а запис вибрано -- SelfcheckError ДО будь-якого запису. Повертає Report (звіт також збережено у файл)."""
    chosen = order(selected_ids)
    writers = [s for s in chosen if s.risk == RISK_WRITE]
    if writers and not ctx.snapshot_ok():
        raise SelfcheckError("сценарії запису недоступні без повного знімка: спершу «Зробити повний знімок». Нічого не записано.")
    started = datetime.datetime.now() if ctx.now is None else ctx.now
    try:
        info = ctx.link.radio_info()
    except cl.CpsError as e:
        raise SelfcheckError("рація не відповідає: %s" % e)
    write_ok = True
    if writers:
        write_ok = bool(confirm_writes and confirm_writes(writes_confirmation_text([s.sid for s in chosen], ctx.snapshot["path"])))
    results = []
    inv_before = snapshot_invariants(ctx.link) if writers and write_ok else None
    n = len(chosen)
    for k, sc in enumerate(chosen):
        res = Result(sc)
        results.append(res)
        if cancel and cancel():
            res.skip_reason = "прогін скасовано"
            continue
        if sc.risk == RISK_WRITE and not write_ok:
            res.skip_reason = "запис не підтверджено"
            continue
        if sc.risk == RISK_WRITE and ctx.halted:
            res.skip_reason = "зупинено: " + ctx.halted
            continue
        ctx.progress(100.0 * k / n, "%s %s" % (sc.sid, sc.title))
        ctx.log("=== %s %s [%s]" % (sc.sid, sc.title, RISK_TEXT[sc.risk]))
        t0 = time.time()
        res._t = t0
        try:
            sc.func(ctx, res)
        except (rs.RestoreInterrupted,) as e:
            res.interrupted = True
            res.error = "ЗАПИС ОБІРВАНО: " + str(e).splitlines()[0]
            ctx.shout("%s: запис обірвано -- рація може бути у проміжному стані. %s" % (sc.sid, " ".join(str(e).splitlines()[1:4])))
            ctx.halted = "рація у проміжному стані після %s" % sc.sid
        except Exception as e:  # noqa: BLE001 -- збій сценарію не має валити весь прогін; текст іде у звіт
            res.error = "%s: %s" % (type(e).__name__, e)
            ctx.log(traceback.format_exc())
            if sc.risk == RISK_WRITE:
                ctx.shout("%s: збій під час сценарію запису (%s). Перевірте стан рації; страхова копія/знімок: %s" % (sc.sid, e, (ctx.snapshot or {}).get("path", "?")))
                ctx.halted = "збій під час %s" % sc.sid
        res.seconds = round(time.time() - t0, 1)
        if sc.risk == RISK_WRITE:
            ctx.invalidate()
        ctx.log("    %s" % STATUS_TEXT[res.status])
    invariants = None
    if inv_before is not None:
        if ctx.halted:
            invariants = Result(Scenario("S4.0", "Інваріанти: що сценарії запису не мали чіпати", RISK_READ, None))
            invariants.check("інваріанти після запису", "перевірено", "не перевірялись: " + ctx.halted, False)
        else:
            if ctx.codeplug_written and ctx.post_reset:
                try:
                    rs._send_c(ctx.link, 6, rs.POST_RESTORE_SUB)
                    ctx.log("Рацію перезавантажено (вона показувала екран CPS).")
                except Exception as e:  # noqa: BLE001
                    ctx.log("Перезавантаження не вдалось: %s" % e)
            invariants = invariants_result(inv_before, snapshot_invariants(ctx.link))
    finished = datetime.datetime.now() if ctx.now is None else ctx.now
    rep = Report(ctx, results, started, finished, info, invariants, [s.sid for s in chosen])
    path = save_report(rep)
    ctx.progress(100, "Звіт: %s" % path)
    ctx.log("Звіт збережено: %s" % path)
    return rep
