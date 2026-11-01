# -*- coding: utf-8 -*-
"""R56: «Оновити супутники» одним натисканням -- логіка без Tk (мережа з кешем, план оновлення слотів у ПАМ'ЯТІ, текст підсумку).

Що робить кнопка (див. cps_ui/p_satellites.py):
  1) TLE: група `amateur` Celestrak одним запитом; для NORAD з таблиці частот, яких у групі нема, -- запит за номером (CATNR). Відповіді кешуються на диску:
     Celestrak не опитується частіше, ніж раз на TLE_CACHE_HOURS (див. нижче про це число);
  2) план: слот, що вже є і має частоти, -- оновлюється ЛИШЕ TLE; слот без частот або супутник, якого в слотах нема, -- додається з таблиці (частоти, тони, шлях APRS);
     рядок таблиці без TLE -- пропускається й перелічується; слоти поза таблицею (ручні) -- не чіпаються; понад 25 -- не додається;
     частоти слота, що відрізняються від таблиці, НЕ змінюються: їх лише рахує й показує підсумок.
  Нічого не записується в рацію: запис -- окремий крок панелі, тим самим безпечним шляхом (sat_tle.write_slots: страхова копія, звірка читанням).

TLE_CACHE_HOURS = 2 -- ГІПОТЕЗА, не звірена з правилами Celestrak (з середовища розробки Celestrak закритий для робота). Перевір на сторінці правил використання
https://celestrak.org/usage-policy.php і, якщо там інше, зміни константу."""
import datetime
import os
import urllib.error
import urllib.request

import sat_table as stb
import sat_tle as st

CELESTRAK_CATNR = "https://celestrak.org/NORAD/elements/gp.php?CATNR=%d&FORMAT=tle"
TLE_CACHE_HOURS = 2                  # не опитувати Celestrak частіше (гіпотеза, див. docstring)
NET_TIMEOUT_S = 30
NO_NET_TEXT = "Немає зв'язку. Детально → відкрити файл TLE."
USER_AGENT = "OpenTYT-CPS/R56"
GROUP_KEY = "amateur"


class NetError(st.SatError):
    """Мережа недоступна або сервер відповів помилкою (code -- код HTTP, None -- нема з'єднання)."""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class NotFound(NetError):
    """Сервер відповів 404: такого набору нема."""


def default_fetch(url, timeout=NET_TIMEOUT_S):
    """Завантажити URL -> байти. NetError з пояснювальним текстом; 404 -- NotFound."""
    if not url.lower().startswith(("http://", "https://")):
        raise st.SatError("адреса має починатися з http:// або https://")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound("сервер відповів 404 (такого набору нема)", 404)
        raise NetError("сервер відповів кодом %s" % e.code, e.code)
    except TimeoutError:
        raise NetError("час очікування відповіді вичерпано (%d с)" % timeout)
    except (urllib.error.URLError, OSError) as e:
        raise NetError("з'єднатися не вдалося: %s" % getattr(e, "reason", e))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Кеш на диску
# ---------------------------------------------------------------------------------------------------------------------------------

def _cache_path(cache_dir, key, none=False):
    return os.path.join(cache_dir, "%s.%s" % (key, "none" if none else "tle"))


def _fresh(path, now, hours):
    """Файл існує і не старший за hours відносно now (naive UTC datetime)."""
    try:
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc).replace(tzinfo=None)
    except OSError:
        return False
    age = (now - mt).total_seconds()
    return -300 <= age < hours * 3600           # мітка з майбутнього (збитий годинник) далі ніж на 5 хв -- вважаємо застарілою


def cache_get(cache_dir, key, now, hours=None):
    """-> текст свіжого кешу або None."""
    hours = TLE_CACHE_HOURS if hours is None else hours
    p = _cache_path(cache_dir, key)
    if _fresh(p, now, hours):
        try:
            with open(p, "rb") as f:
                return f.read().decode("utf-8", errors="replace")
        except OSError:
            return None
    return None


def cache_is_none(cache_dir, key, now, hours=None):
    """Свіжа позначка «такого набору нема» (щоб не питати Celestrak про той самий номер знову)."""
    return _fresh(_cache_path(cache_dir, key, none=True), now, TLE_CACHE_HOURS if hours is None else hours)


def cache_put(cache_dir, key, text, none=False, now=None):
    """Записати кеш. now (naive UTC) -- «годинник» оновлення: час зміни файла ставиться за ним, щоб свіжість кешу й тести рахувались одним годинником."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        p = _cache_path(cache_dir, key, none=none)
        tmp = p + ".part"
        with open(tmp, "wb") as f:
            f.write(b"" if none else text.encode("utf-8"))
        os.replace(tmp, p)
        if now is not None:
            ts = now.replace(tzinfo=datetime.timezone.utc).timestamp()
            os.utime(p, (ts, ts))
        if none:
            try:
                os.unlink(_cache_path(cache_dir, key))
            except OSError:
                pass
        else:
            try:
                os.unlink(_cache_path(cache_dir, key, none=True))
            except OSError:
                pass
    except OSError:
        pass                         # кеш -- лише оптимізація: збій запису не має ламати оновлення


# ---------------------------------------------------------------------------------------------------------------------------------
#  Отримання TLE
# ---------------------------------------------------------------------------------------------------------------------------------

class FetchResult:
    def __init__(self):
        self.tles = []               # усі розібрані набори (група + окремі запити)
        self.requests = []           # URL, які справді запитано в мережі (не з кешу)
        self.from_cache = []         # ключі, взяті з кешу
        self.errors = []             # тексти про окремі збої (не про групу)
        self.not_found = []          # NORAD, для яких Celestrak відповів «нема»


def fetch_tles(rows, now, cache_dir, fetch=None, hours=None, group_url=None):
    """Група `amateur` + запити CATNR для NORAD таблиці, яких у групі нема. Збій ГРУПИ -- NetError (зупинка, нічого не змінюється); збій окремого номера --
    запис у result.errors. fetch(url, timeout) -> bytes, за замовчуванням default_fetch (у тестах підміняється)."""
    fetch = fetch or default_fetch
    res = FetchResult()
    # 1. група
    text = cache_get(cache_dir, GROUP_KEY, now, hours)
    if text is not None:
        res.from_cache.append(GROUP_KEY)
    else:
        url = group_url or st.CELESTRAK_AMATEUR
        res.requests.append(url)
        raw = fetch(url, NET_TIMEOUT_S)
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        tles, _notes = st.parse_tle_text(text)
        if not [t for t in tles if t.ok]:
            raise NetError("відповідь Celestrak не схожа на TLE (у ній нема жодного придатного набору)")
        cache_put(cache_dir, GROUP_KEY, text, now=now)
    group, _notes = st.parse_tle_text(text)
    res.tles.extend(group)
    have = {stb.norad_of(t) for t in group if t.ok}
    # 2. окремі запити за номером
    net_down = False
    for r in rows:
        if r.norad in have:
            continue
        key = "catnr_%d" % r.norad
        if cache_is_none(cache_dir, key, now, hours):
            res.from_cache.append(key + " (нема)")
            res.not_found.append(r.norad)
            continue
        text = cache_get(cache_dir, key, now, hours)
        if text is not None:
            res.from_cache.append(key)
        else:
            if net_down:
                res.errors.append("%s (%d): не запитано -- мережа зникла під час оновлення" % (r.name, r.norad))
                continue
            url = CELESTRAK_CATNR % r.norad
            res.requests.append(url)
            try:
                raw = fetch(url, NET_TIMEOUT_S)
            except NotFound:
                cache_put(cache_dir, key, "", none=True, now=now)
                res.not_found.append(r.norad)
                continue
            except NetError as e:
                if e.code is None:
                    net_down = True
                res.errors.append("%s (%d): %s" % (r.name, r.norad, e))
                continue
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            good = [t for t in st.parse_tle_text(text)[0] if t.ok]
            if not good:
                cache_put(cache_dir, key, "", none=True, now=now)
                res.not_found.append(r.norad)
                continue
            cache_put(cache_dir, key, text, now=now)
        res.tles.extend(st.parse_tle_text(text)[0])
        have.add(r.norad)
    return res


# ---------------------------------------------------------------------------------------------------------------------------------
#  План оновлення (у пам'яті)
# ---------------------------------------------------------------------------------------------------------------------------------

class UpdatePlan:
    def __init__(self):
        self.slots = []              # новий список слотів (нічого не записано)
        self.updated = []            # [(ім'я, вік до (діб|None), вік після)] лише TLE
        self.added = []              # [(ім'я, вік, "новий" | "слот без частот заповнено з таблиці")]
        self.unchanged = []          # [(ім'я, причина)]
        self.missing = []            # [(ім'я, NORAD)] немає TLE
        self.differs = []            # [(ім'я, [що відрізняється])]
        self.manual = []             # імена слотів поза таблицею (не чіпаємо)
        self.ambiguous = []          # імена, що повторюються в слотах (не чіпаємо)
        self.dropped = []            # імена, що не влізли (понад 25)
        self.errors = []             # помилки перевірки R54 F2.4 (блокують запис)
        self.warns = []
        self.nofreq = []

    @property
    def changed(self):
        return bool(self.updated or self.added)


def _best_by_norad(tles):
    best = {}
    for t in tles:
        if not t.ok:
            continue
        k = stb.norad_of(t)
        if k is None:
            continue
        cur = best.get(k)
        if cur is None or (t.epoch is not None and (cur.epoch is None or t.epoch > cur.epoch)):
            best[k] = t
    return best


def _differences(slot, row):
    """Які поля слота відрізняються від рядка таблиці (імена полів). Шлях APRS порівнюється, лише коли в таблиці він заданий."""
    out = []
    pairs = (("RX1", slot.rx1, row.rx1), ("TX1", slot.tx1, row.tx1), ("субтон передачі", slot.ctcss, row.ctcss), ("субтон взведення", slot.arm, row.arm),
             ("APRS RX", slot.rx2, row.rx2), ("APRS TX", slot.tx2, row.tx2), ("маяк RX", slot.rx3, row.rx3), ("маяк TX", slot.tx3, row.tx3))
    for nm, a, b in pairs:
        if int(a) != int(b):
            out.append(nm)
    if row.aprs:
        try:
            want = stb.encode_aprs(row.aprs, slot.extra)
            if bytes(want)[:14] != bytes(slot.extra)[:14]:
                out.append("шлях APRS")
        except st.SatError:
            pass
    return out


def build_plan(slots, rows, tles, now=None):
    """Побудувати план у пам'яті. slots не змінюються; результат -- plan.slots. Порядок: за рядками таблиці."""
    best = _best_by_norad(tles)
    out = [s.copy() for s in slots]
    plan = UpdatePlan()
    names = {}
    for i, s in enumerate(out):
        names.setdefault(st.norm_name(s.name), []).append(i)
    in_table = set()
    for r in rows:
        key = st.norm_name(r.name)
        in_table.add(key)
        tle = best.get(r.norad)
        if tle is None:
            plan.missing.append((r.name, r.norad))
            continue
        idxs = names.get(key, [])
        if len(idxs) > 1:
            plan.ambiguous.append(r.name)
            continue
        if not idxs:
            if len(out) >= st.NUM_SLOTS:
                plan.dropped.append(r.name)
                continue
            s = st.Slot.from_tle(tle, name=r.name)
            stb.fill_slot(s, r)
            out.append(s)
            names.setdefault(key, []).append(len(out) - 1)
            plan.added.append((r.name, st.age_level(s, now)[0], "новий слот"))
            continue
        i = idxs[0]
        old = out[i]
        old_days = st.age_level(old, now)[0]
        if not stb.slot_has_freqs(old) and stb.slot_is_blank(old):
            s = st.Slot.from_tle(tle, name=old.name)
            stb.fill_slot(s, r)
            out[i] = s
            plan.added.append((r.name, st.age_level(s, now)[0], "слот без частот заповнено з таблиці"))
            continue
        # слот має частоти (або в ньому є ручні тони/шлях): оновлюється лише TLE, решту не чіпаємо
        diff = _differences(old, r)
        if diff:
            plan.differs.append((old.name, diff))
        oe, ne = old.epoch, tle.epoch
        if ne is None or (oe is not None and ne < oe):
            plan.unchanged.append((old.name, "у слоті свіжіший TLE"))
        elif oe is not None and ne == oe and st.fields1_text(tle.line1) == old.l1 and st.fields2_text(tle.line2) == old.l2:
            plan.unchanged.append((old.name, "TLE той самий"))
        else:
            new = st.Slot.from_tle(tle, name=old.name, keep=old)
            out[i] = new
            plan.updated.append((old.name, old_days, st.age_level(new, now)[0]))
    plan.manual = [s.name for s in out if st.norm_name(s.name) not in in_table]
    plan.slots = out
    plan.errors, plan.warns, plan.nofreq = stb.validate_slots(out)
    return plan


# ---------------------------------------------------------------------------------------------------------------------------------
#  Тексти
# ---------------------------------------------------------------------------------------------------------------------------------

def _days(n):
    return "?" if n is None else "%d" % n


def plan_text(plan, now=None):
    """Підсумок для вікна. Рядки «Оновлено TLE», «Додано», «Без змін», «Немає TLE», «Частоти відрізняються від таблиці» -- лише коли є що сказати,
    «Без змін» -- завжди."""
    lines = []
    if plan.updated:
        lines.append("Оновлено TLE: %s." % ", ".join("%s (вік було %s дн., стало %s дн.)" % (n, _days(a), _days(b)) for n, a, b in plan.updated))
    else:
        lines.append("Оновлено TLE: нічого.")
    if plan.added:
        lines.append("Додано: %s." % ", ".join("%s (%s, вік TLE %s дн.)" % (n, why, _days(a)) for n, a, why in plan.added))
    lines.append("Без змін: %s." % (", ".join("%s (%s)" % x for x in plan.unchanged) or "нічого"))
    if plan.missing:
        lines.append("Немає TLE: %s. Це не помилка (напр., супутник зійшов з орбіти); їх пропущено." % ", ".join("%s (%d)" % x for x in plan.missing))
    if plan.differs:
        lines.append("Частоти відрізняються від таблиці (слоти НЕ змінено, це лише повідомлення): %s." % "; ".join(
            "%s: %s" % (n, ", ".join(d)) for n, d in plan.differs))
    if plan.ambiguous:
        lines.append("Назва повторюється в слотах -- не чіпаю: %s." % ", ".join(plan.ambiguous))
    if plan.manual:
        lines.append("Поза таблицею (ручні) -- не чіпаю: %s." % ", ".join(plan.manual))
    if plan.dropped:
        lines.append("Не влізло (слотів лише %d), не додано: %s." % (st.NUM_SLOTS, ", ".join(plan.dropped)))
    if plan.errors:
        lines.append("ПОМИЛКИ перевірки частот (запис у рацію неможливий, поки їх не виправлено в «Детально»):\n  " + "\n  ".join(plan.errors))
    return "\n".join(lines)


def radio_status_text(slots, radio_state, now=None):
    """Рядок стану рації для головного вигляду -> (текст, рівень: ok | stale | old | none)."""
    if radio_state is None:
        return "Рація не прочитана", "none"
    if not slots:
        return "У рації: 0 супутників", "none"
    worst, level = None, st.AGE_OK
    order = {st.AGE_OK: 0, st.AGE_UNKNOWN: 0, st.AGE_STALE: 1, st.AGE_OLD: 2}
    for s in slots:
        d, lvl = st.age_level(s, now)
        if d is not None and (worst is None or d > worst):
            worst = d
        if order[lvl] > order[level]:
            level = lvl
    word = {st.AGE_OK: "ok", st.AGE_UNKNOWN: "ok", st.AGE_STALE: "stale", st.AGE_OLD: "old"}[level]
    return "У рації: %d %s, найстаріший TLE: %s діб" % (len(slots), _plural_sat(len(slots)), _days(worst)), word


def _plural_sat(n):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "супутник"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return "супутники"
    return "супутників"


def done_text(slots, now=None):
    """Рядок після запису й перечитування: «Готово: N супутників, найстаріший TLE X діб»."""
    worst = None
    for s in slots:
        d = st.age_level(s, now)[0]
        if d is not None and (worst is None or d > worst):
            worst = d
    return "Готово: %d %s, найстаріший TLE %s діб." % (len(slots), _plural_sat(len(slots)), _days(worst))
