#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R56: «Оновити супутники» -- логіка без Tk і без рації (sat_update.py): мережа з підміною, кеш на диску, план оновлення в пам'яті, тексти. Хост-тести.

G1  мережа: група amateur + запити CATNR для номерів таблиці, яких у групі нема; 404 -- «нема TLE», не помилка;
G2  кеш: повторне натискання в межах інтервалу не робить жодного запиту (і не питає про номер, що вже дав 404); після інтервалу -- питає знову; МУТАНТИ інтервалу й мітки «нема»;
G3  без мережі: збій групи -- NetError (нічого не змінюється, застарілий кеш мовчки не використовується); збій окремого номера -- запис про помилку, решта триває;
G4  план: слот з частотами -- оновлюється лише TLE (частоти, тони, шлях APRS побайтово ті самі); порожній слот і відсутній супутник -- додаються з таблиці; рядок без TLE -- пропущено й названо;
    ручні слоти поза таблицею не чіпаються; понад 25 не додається; частоти слота, що відрізняються від таблиці, не змінюються, а лише рахуються; повтор назви -- не чіпаємо;
G5  тексти підсумку (рядки «Оновлено TLE», «Додано», «Без змін», «Немає TLE», «Частоти відрізняються від таблиці»), рядок стану рації, множина «супутник/супутники/супутників»;
G6  МУТАНТИ плану (перезапис частот при оновленні, зміна ручних слотів, відсутність ліміту 25, відсутність порівняння частот): тест їх бачить;
G8  справжній default_fetch проти локального HTTP-сервера: 200, 404 (NotFound), 500 (NetError з кодом), таймаут, відмова з'єднання -- зрозумілі повідомлення;
G7  підключено до tests/run_tests.sh, у TESTING.md є кроки DE1..DE5.
Запуск: python3 tools/test_r56.py"""
import datetime
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FW = os.path.dirname(HERE)
FAILS = []
PASSED = [0]

import sat_table as stb          # noqa: E402
import sat_tle as st             # noqa: E402
import sat_update as su          # noqa: E402
import test_r35 as t35           # noqa: E402

NOW = datetime.datetime(2026, 11, 1)            # день року 305


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def tle_text(items):
    """items: [(назва, NORAD, вік у добах)] -> текст TLE (3 рядки на набір)."""
    out = []
    for nm, n, age in items:
        a, l1, l2 = t35.mk_tle(nm, n, 26, float(305 - age))
        out += [a, l1, l2]
    return "\n".join(out) + "\n"


NAMES = {43017: "AO-91", 61781: "AO-123", 25544: "ISS (ZARYA)", 40908: "LILACSAT-2", 43678: "PO-101", 27607: "SAUDISAT 1C (SO-50)", 59112: "SONATE-2", 57172: "UMKA-1"}


class Net:
    """Підміна мережі: routes {url: bytes | Exception}; calls -- що справді запитали."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout=30):
        self.calls.append(url)
        r = self.routes.get(url)
        if r is None:
            raise su.NotFound("404", 404)
        if isinstance(r, Exception):
            raise r
        return r


def make_routes(group_nums, extra=None, age=1):
    routes = {st.CELESTRAK_AMATEUR: tle_text([(NAMES[n], n, age) for n in group_nums]).encode()}
    for n, v in (extra or {}).items():
        routes[su.CELESTRAK_CATNR % n] = v
    return routes


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def rows():
    return stb.default_rows()[0]


# ---------------------------------------------------------------------------------------------------------------------------------
def test_g1_g3_net():
    rs = rows()
    group = [43017, 61781, 25544, 40908, 43678, 27607]                  # у групі 6 із 8; 59112 і 57172 -- окремі запити
    d = tempfile.mkdtemp(prefix="r56c_")
    net = Net(make_routes(group, {59112: tle_text([("SONATE-2", 59112, 1)]).encode(), 57172: su.NotFound("404", 404)}))
    base = utcnow()
    res = su.fetch_tles(rs, base, d, fetch=net)
    check(net.calls == [st.CELESTRAK_AMATEUR, su.CELESTRAK_CATNR % 59112, su.CELESTRAK_CATNR % 57172], "G1: запити -- група, потім CATNR для відсутніх у порядку таблиці: %r" % net.calls)
    check(len([t for t in res.tles if t.ok]) == 7 and res.not_found == [57172] and not res.errors, "G1: 7 наборів, 57172 -- 404 (не помилка): %r %r" % (len(res.tles), res.not_found))
    check(res.requests == net.calls and not res.from_cache, "G1: result.requests збігається з реальними запитами")
    # --- G2: кеш ---
    net2 = Net(make_routes([], {}))
    res2 = su.fetch_tles(rs, base + datetime.timedelta(minutes=119), d, fetch=net2)
    check(net2.calls == [] and len([t for t in res2.tles if t.ok]) == 7, "G2: за 1 год 59 хв -- жодного запиту, дані з кешу (%r)" % net2.calls)
    check(su.GROUP_KEY in res2.from_cache and 57172 in res2.not_found, "G2: 404 теж у кеші -- про 57172 не питаємо знову")
    net3 = Net(make_routes(group, {59112: tle_text([("SONATE-2", 59112, 1)]).encode()}))
    su.fetch_tles(rs, base + datetime.timedelta(minutes=121), d, fetch=net3)
    check(len(net3.calls) == 3, "G2: за 2 год 01 хв -- запитуємо знову (%d запитів)" % len(net3.calls))
    # --- G2 мутанти ---
    old = su.TLE_CACHE_HOURS
    try:
        su.TLE_CACHE_HOURS = 0
        d0 = tempfile.mkdtemp(prefix="r56c0_")
        su.fetch_tles(rs, base, d0, fetch=Net(make_routes(group, {59112: tle_text([("SONATE-2", 59112, 1)]).encode()})))
        n0 = Net(make_routes(group, {59112: tle_text([("SONATE-2", 59112, 1)]).encode()}))
        su.fetch_tles(rs, base + datetime.timedelta(minutes=1), d0, fetch=n0)
        check(len(n0.calls) > 0, "G2/мутант: інтервал 0 -- повторне натискання знову йде в мережу (тест це бачить)")
    finally:
        su.TLE_CACHE_HOURS = old
    old_none = su.cache_is_none
    try:
        su.cache_is_none = lambda *a, **k: False
        n1 = Net(make_routes([], {}))
        d1 = tempfile.mkdtemp(prefix="r56c1_")
        su.fetch_tles(rs, base, d1, fetch=Net(make_routes(group, {59112: tle_text([("SONATE-2", 59112, 1)]).encode()})))
        su.fetch_tles(rs, base + datetime.timedelta(minutes=5), d1, fetch=n1)
        check(any("57172" in u for u in n1.calls), "G2/мутант: без мітки «нема» номер 57172 запитується знову (тест це бачить)")
    finally:
        su.cache_is_none = old_none
    # --- G3: без мережі ---
    d3 = tempfile.mkdtemp(prefix="r56c3_")
    down = Net({st.CELESTRAK_AMATEUR: su.NetError("з'єднатися не вдалося: Name or service not known")})
    raised = None
    try:
        su.fetch_tles(rs, base, d3, fetch=down)
    except su.NetError as e:
        raised = e
    check(raised is not None and "з'єднатися" in str(raised) and not os.listdir(d3), "G3: збій групи -- NetError, кеш порожній: %r" % raised)
    # застарілий кеш мовчки не використовується
    d4 = tempfile.mkdtemp(prefix="r56c4_")
    su.fetch_tles(rs, base, d4, fetch=Net(make_routes(group, {59112: tle_text([("SONATE-2", 59112, 1)]).encode()})))
    raised = None
    try:
        su.fetch_tles(rs, base + datetime.timedelta(hours=3), d4, fetch=down)
    except su.NetError as e:
        raised = e
    check(raised is not None, "G3: інтервал минув, мережі нема -- зупинка, а не мовчазне використання старого кешу")
    # збій окремого номера: мережа зникла після групи
    d5 = tempfile.mkdtemp(prefix="r56c5_")
    routes = make_routes(group, {59112: su.NetError("час очікування відповіді вичерпано (30 с)"), 57172: tle_text([("UMKA-1", 57172, 1)]).encode()})
    n5 = Net(routes)
    r5 = su.fetch_tles(rs, base, d5, fetch=n5)
    check(len(r5.errors) == 2 and "SONATE-2" in r5.errors[0] and "57172" in r5.errors[1] and len(n5.calls) == 2,
          "G3: мережа зникла на першому окремому запиті -- другий не робимо (%r, запитів %d)" % (r5.errors, len(n5.calls)))
    # HTTP 500 на одному номері -- решта триває
    d6 = tempfile.mkdtemp(prefix="r56c6_")
    n6 = Net(make_routes(group, {59112: su.NetError("сервер відповів кодом 500", 500), 57172: tle_text([("UMKA-1", 57172, 1)]).encode()}))
    r6 = su.fetch_tles(rs, base, d6, fetch=n6)
    check(len(r6.errors) == 1 and "500" in r6.errors[0] and len(n6.calls) == 3 and 57172 not in r6.not_found, "G3: код 500 на одному номері -- решта триває: %r" % (r6.errors,))
    # відповідь-сміття
    d7 = tempfile.mkdtemp(prefix="r56c7_")
    raised = None
    try:
        su.fetch_tles(rs, base, d7, fetch=Net({st.CELESTRAK_AMATEUR: b"<html>Service unavailable</html>"}))
    except su.NetError as e:
        raised = e
    check(raised is not None and "не схожа на TLE" in str(raised) and not os.listdir(d7), "G3: сміття замість TLE -- NetError, у кеш не потрапляє")
    check(su.NO_NET_TEXT == "Немає зв'язку. Детально → відкрити файл TLE.", "G3: текст без мережі -- як у брифі")


# ---------------------------------------------------------------------------------------------------------------------------------
def slot_from(nm, norad, age, row=None, **over):
    t = st.Tle(*t35.mk_tle(NAMES.get(norad, nm), norad, 26, float(305 - age)))
    s = st.Slot.from_tle(t, name=nm)
    if row is not None:
        stb.fill_slot(s, row)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def tles(items):
    return [st.Tle(*t35.mk_tle(NAMES[n], n, 26, float(305 - age))) for n, age in items]


def freq_key(s):
    return (s.rx1, s.tx1, s.ctcss, s.arm, s.rx2, s.tx2, s.rx3, s.tx3, bytes(s.extra))


def plan_checks(build=su.build_plan):
    """Усі перевірки плану; повертає список невдач (порожній -- усе гаразд). Приймає реалізацію build_plan, щоб мутанти проганялись тими самими перевірками."""
    bad = []
    count = [0]

    def chk(c, m):
        count[0] += 1
        if not c:
            bad.append(m)
    rs = rows()
    by = {r.name: r for r in rs}
    # слоти: AO-91 з ручною частотою і старим TLE (20 діб), ISS порожній, «MYSAT» ручний; SO-50 свіжіший TLE, ніж у файлі
    ao91 = slot_from("AO-91", 43017, 20, by["AO-91"], rx1=145_970_000)         # користувач змінив RX1
    iss_blank = slot_from("ISS", 25544, 30)                                    # без частот
    my = slot_from("MYSAT", 43017, 5, None, rx1=145_500_000, tx1=145_500_000, ctcss=1000)
    so_fresh = slot_from("SO-50", 27607, 0, by["SO-50"])                       # у слоті епоха свіжіша за файл
    slots = [ao91, iss_blank, my, so_fresh]
    before = [s.pack() for s in slots]
    new_t = tles([(43017, 1), (25544, 1), (27607, 3), (61781, 1), (40908, 2)])   # 43678, 59112, 57172 -- без TLE
    plan = build(slots, rs, new_t, NOW)
    chk([s.pack() for s in slots] == before, "G4: вхідні слоти не змінено")
    names = [s.name for s in plan.slots]
    chk(names[:4] == ["AO-91", "ISS", "MYSAT", "SO-50"], "G4: порядок наявних слотів зберігається: %r" % names)
    # AO-91: оновлено лише TLE
    a = plan.slots[0]
    chk(freq_key(a) == freq_key(ao91) and a.rx1 == 145_970_000, "G4: слот з частотами -- частоти, тони, шлях APRS побайтово ті самі (ручний RX1 лишився)")
    chk(a.l1 != ao91.l1 and abs(a.age_days(NOW) - 1) < 0.01, "G4: TLE AO-91 оновлено (вік 1 доба)")
    chk(any(n == "AO-91" and o == 20 and nw == 1 for n, o, nw in plan.updated), "G4: «оновлено» називає вік було/стало: %r" % (plan.updated,))
    chk(any(n == "AO-91" and "RX1" in d for n, d in plan.differs), "G4: розбіжність RX1 з таблицею лише показано: %r" % (plan.differs,))
    # ISS: порожній -> з таблиці
    i = plan.slots[1]
    chk(i.rx1 == by["ISS"].rx1 and i.tx1 == by["ISS"].tx1 and i.ctcss == by["ISS"].ctcss and stb.decode_aprs(i.extra) == by["ISS"].aprs, "G4: порожній слот заповнено частотами, тоном і шляхом з таблиці")
    chk(any(n == "ISS" for n, _a, why in plan.added if "заповнено" in why), "G4: у «Додано» названо як заповнений")
    # ручний слот поза таблицею
    chk(plan.slots[2].pack() == my.pack() and "MYSAT" in plan.manual, "G4: ручний слот поза таблицею не чіпається")
    # SO-50: у слоті свіжіше
    chk(plan.slots[3].pack() == so_fresh.pack() and any(n == "SO-50" and "свіжіший" in why for n, why in plan.unchanged), "G4: свіжіший TLE у слоті не замінюється файлом")
    # нові з таблиці: AO-123, LilacSat
    added = [n for n, _a, _w in plan.added]
    chk("AO-123" in added and "LilacSat" in added, "G4: відсутні в слотах супутники додано з таблиці: %r" % added)
    ao123 = [s for s in plan.slots if s.name == "AO-123"][0]
    chk(ao123.rx1 == by["AO-123"].rx1 and ao123.rx3 == 0 and ao123.ctcss == 670, "G4: новий слот має частоти й тони з таблиці")
    # без TLE
    miss = {n for n, _k in plan.missing}
    chk(miss == {"PO-101", "SONATE-2", "UmKA-1"} and not any(s.name in miss for s in plan.slots), "G4: рядки таблиці без TLE пропущено й перелічено: %r" % (plan.missing,))
    # той самий TLE -> без змін
    p2 = build(plan.slots, rs, new_t, NOW)
    chk(not p2.updated and not p2.added and not p2.changed, "G4: повторний прохід тими самими TLE нічого не міняє (%r %r)" % (p2.updated, p2.added))
    chk(any("той самий" in why for _n, why in p2.unchanged), "G4: причина «TLE той самий»")
    # повтор назви
    dup = [slot_from("AO-91", 43017, 20, by["AO-91"]), slot_from("AO-91", 43017, 22, by["AO-91"])]
    p3 = build(dup, rs, tles([(43017, 1)]), NOW)
    chk(p3.ambiguous == ["AO-91"] and [s.pack() for s in p3.slots] == [s.pack() for s in dup], "G4: назва, що повторюється, -- не чіпаємо")
    # понад 25
    full = [slot_from("M%d" % k, 43017, 5, None, rx1=145_500_000, tx1=145_500_000) for k in range(25)]
    p4 = build(full, rs, tles([(43017, 1), (25544, 1)]), NOW)
    chk(len(p4.slots) == 25 and p4.dropped == ["AO-91", "ISS"] and not p4.added, "G4: слотів 25 -- нічого не додається, пропущені названі: %r" % (p4.dropped,))
    # помилка перевірки R54 у збереженому ручному слоті блокує запис
    badslot = slot_from("AO-91", 43017, 20, by["AO-91"], rx1=100_000_000)
    p5 = build([badslot], rs, tles([(43017, 1)]), NOW)
    chk(p5.errors and p5.slots[0].rx1 == 100_000_000, "G4: хибна ручна частота не виправляється мовчки, а дає помилку перевірки")
    return bad, count[0]


def test_g4_g6_plan():
    bad, n = plan_checks()
    for b in bad:
        check(False, b)
    PASSED[0] += n - len(bad)
    # --- G6: мутанти ---
    def m_overwrite(slots, rs, tl, now=None):                  # мутант: оновлення перезаписує частоти з таблиці
        p = su.build_plan(slots, rs, tl, now)
        tab = {st.norm_name(r.name): r for r in rs}
        for s in p.slots:
            r = tab.get(st.norm_name(s.name))
            if r:
                stb.fill_slot(s, r)
        return p

    def m_touch_manual(slots, rs, tl, now=None):              # мутант: ручні слоти скидаються
        p = su.build_plan(slots, rs, tl, now)
        for s in p.slots:
            if s.name in p.manual:
                s.rx1 = 0
        return p

    def m_nolimit(slots, rs, tl, now=None):                   # мутант: ліміт 25 не діє
        old = st.NUM_SLOTS
        st.NUM_SLOTS = 40
        try:
            return su.build_plan(slots, rs, tl, now)
        finally:
            st.NUM_SLOTS = old

    def m_nodiff(slots, rs, tl, now=None):                    # мутант: розбіжності не рахуються
        p = su.build_plan(slots, rs, tl, now)
        p.differs = []
        return p

    def m_missing_slot(slots, rs, tl, now=None):              # мутант: рядок без TLE створює порожній слот
        p = su.build_plan(slots, rs, tl, now)
        for n, _k in p.missing:
            p.slots.append(st.Slot(n))
        return p
    for nm, fn in (("перезапис частот при оновленні", m_overwrite), ("скидання ручних слотів", m_touch_manual), ("відсутній ліміт 25", m_nolimit),
                   ("розбіжності не рахуються", m_nodiff), ("слот для рядка без TLE", m_missing_slot)):
        check(len(plan_checks(fn)[0]) > 0, "G6/мутант: %s -- тест це бачить" % nm)


def test_g5_texts():
    rs = rows()
    by = {r.name: r for r in rs}
    slots = [slot_from("AO-91", 43017, 20, by["AO-91"], rx1=145_970_000), slot_from("ISS", 25544, 30)]
    plan = su.build_plan(slots, rs, tles([(43017, 1), (25544, 1), (61781, 1)]), NOW)
    t = su.plan_text(plan, NOW)
    pos = [t.find(k) for k in ("Оновлено TLE:", "Додано:", "Без змін:", "Немає TLE:", "Частоти відрізняються від таблиці")]
    check(all(p >= 0 for p in pos) and pos == sorted(pos), "G5: усі п'ять рядків підсумку в порядку з брифу: %r" % pos)
    check("AO-91 (вік було 20 дн., стало 1 дн.)" in t, "G5: вік нових TLE показано")
    check("Це не помилка" in t and "PO-101" in t, "G5: «Немає TLE» названо і пояснено")
    plan2 = su.build_plan([], rs, [], NOW)
    t2 = su.plan_text(plan2, NOW)
    check("Оновлено TLE: нічого." in t2 and "Без змін: нічого." in t2 and "Частоти відрізняються" not in t2, "G5: порожній план -- «нічого», розбіжностей нема")
    # рядок стану
    check(su.radio_status_text([], None, NOW) == ("Рація не прочитана", "none"), "G5: слоти не прочитані -- «Рація не прочитана»")
    old = [slot_from("A", 43017, 12), slot_from("B", 25544, 1), slot_from("C", 27607, 40)]
    txt, lvl = su.radio_status_text(old, st.ST_OK, NOW)
    check(txt == "У рації: 3 супутники, найстаріший TLE: 40 діб" and lvl == "old", "G5: рядок стану, червоний: %r %s" % (txt, lvl))
    txt, lvl = su.radio_status_text(old[:1], st.ST_OK, NOW)
    check(txt == "У рації: 1 супутник, найстаріший TLE: 12 діб" and lvl == "stale", "G5: жовтий: %r %s" % (txt, lvl))
    txt, lvl = su.radio_status_text(old[1:2], st.ST_OK, NOW)
    check(lvl == "ok" and "найстаріший TLE: 1 діб" in txt, "G5: свіжий TLE -- звичайний колір: %r %s" % (txt, lvl))
    check(su.radio_status_text([], st.ST_OK, NOW)[0] == "У рації: 0 супутників", "G5: порожній блок")
    for n, w in ((1, "супутник"), (2, "супутники"), (5, "супутників"), (11, "супутників"), (12, "супутників"), (21, "супутник"), (24, "супутники"), (25, "супутників")):
        check(su._plural_sat(n) == w, "G5: множина %d -> %s" % (n, w))
    check(su.done_text(old, NOW) == "Готово: 3 супутники, найстаріший TLE 40 діб.", "G5: «Готово: N супутників, найстаріший TLE X діб»: %s" % su.done_text(old, NOW))


def test_g8_default_fetch():
    import http.server
    import threading
    import time

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/ok":
                body = tle_text([("AO-91", 43017, 1)]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/slow":
                time.sleep(3)
                self.send_response(200)
                self.end_headers()
            elif self.path == "/err":
                self.send_response(500)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = "http://127.0.0.1:%d" % port
        raw = su.default_fetch(base + "/ok", 5)
        check(b"AO-91" in raw, "G8: 200 -- тіло отримано")

        def err(path, timeout=5):
            try:
                su.default_fetch(base + path, timeout)
            except su.NetError as e:
                return e
            return None
        e = err("/nope")
        check(isinstance(e, su.NotFound) and e.code == 404, "G8: 404 -- NotFound: %r" % e)
        e = err("/err")
        check(e is not None and not isinstance(e, su.NotFound) and e.code == 500 and "500" in str(e), "G8: 500 -- NetError з кодом: %r" % e)
        e = err("/slow", 1)
        check(e is not None and e.code is None and "час очікування" in str(e), "G8: таймаут -- зрозуміле повідомлення: %r" % e)
    finally:
        srv.shutdown()
        srv.server_close()
    # відмова з'єднання: порт, на якому нікого нема
    import socket
    sck = socket.socket()
    sck.bind(("127.0.0.1", 0))
    dead = sck.getsockname()[1]
    sck.close()
    try:
        su.default_fetch("http://127.0.0.1:%d/x" % dead, 3)
        e = None
    except su.NetError as ex:
        e = ex
    check(e is not None and e.code is None and "з'єднатися не вдалося" in str(e), "G8: відмова з'єднання -- NetError без коду: %r" % e)
    try:
        su.default_fetch("ftp://x/y")
        e = None
    except st.SatError as ex:
        e = ex
    check(e is not None and "http" in str(e), "G8: не-http адреса відхилено")


def test_g7_wiring():
    with open(os.path.join(FW, "tests", "run_tests.sh"), encoding="utf-8") as f:
        sh = f.read()
    check("test_r56" in sh and "test_r56_ui" in sh, "G7: test_r56 і test_r56_ui підключено до tests/run_tests.sh")
    with open(os.path.join(os.path.dirname(FW), "TESTING.md"), encoding="utf-8") as f:
        tm = f.read()
    check(all(("| DE%d |" % k) in tm for k in range(1, 6)), "G7: у TESTING.md є кроки DE1..DE5")


def main():
    for t in (test_g1_g3_net, test_g4_g6_plan, test_g5_texts, test_g8_default_fetch, test_g7_wiring):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        return 1
    print("test_r56: усе гаразд (%d перевірок: мережа й кеш, план оновлення, тексти, мутанти)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
