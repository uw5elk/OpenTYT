# -*- coding: utf-8 -*-
"""R34 (Z1-Z5): байт 0xFF у назвах -- мала «я» в cp1251 («Поляна», «Зоря», «Надія», «Земля»).

ПРОШИВКА перевіряється на СПРАВЖНЬОМУ коді: з application/source/functions/codeplug.c витягуються codeplugUtilConvertBufToString (+ допоміжні) і
codeplugUtilConvertStringToBuf, компілюються gcc у трьох варіантах (стоковий; APRS_R21_NAMES; APRS_R21_NAMES + CODEPLUG_NAME_ZERO_TAIL) і ганяються на тих самих
буферах. Стоковий варіант у тесті відтворює вади (обрізання «Пол», псування вхідного буфера) -- це доводить, що тест їх справді бачить.
CPS (tools/) перевіряється ДИФЕРЕНЦІЙНО проти скомпільованого коду прошивки на випадкових буферах і на кодплазі-фікстурі.
Потрібен gcc (без нього частина прошивки пропускається з повідомленням). Запуск: python3 tools/test_r34.py (GUI не потрібен)."""
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import codeplug_view as cv               # noqa: E402
import contact_edit as ce                # noqa: E402
import cps_csv as cc                     # noqa: E402
import table_edit as te                  # noqa: E402

FAILS = []
APP = os.path.normpath(os.path.join(HERE, "..", "application"))
CODEPLUG_C = os.path.join(APP, "source", "functions", "codeplug.c")
CODEPLUG_H = os.path.join(APP, "include", "functions", "codeplug.h")
VARIANTS = {"stock": [], "r21": ["-DAPRS_R21_NAMES"], "r21zt": ["-DAPRS_R21_NAMES", "-DCODEPLUG_NAME_ZERO_TAIL"]}
HARNESS = {}


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def cp(s):
    return s.encode("cp1251")


def tail(raw, fill, n=16):
    return raw + bytes([fill]) * (n - len(raw))


# ----------------------------------------------------------------------------------------------------------------------
#  Збірка харнесу з РЕАЛЬНОГО codeplug.c
# ----------------------------------------------------------------------------------------------------------------------

def extract_sources():
    src = open(CODEPLUG_C, encoding="utf-8", errors="replace").read()
    a = src.index("#if defined(APRS_R21_NAMES)\n/* R34 N2")
    b = src.index("#if defined(APRS_R21_NAMES)\nvoid codeplugUtilConvertBufToDisplayString")
    c = src.index("#if defined(APRS_R21_NAMES) && defined(CODEPLUG_NAME_ZERO_TAIL)")
    d = src.index("void codeplugZonesInitCache(void)")
    return src[a:b] + "\n" + src[c:d]


MAIN = r"""
static int hexv(char c) { return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : c - 'A' + 10; }
static int unhex(const char *h, unsigned char *out) { int n = (int)strlen(h) / 2; for (int i = 0; i < n; i++) out[i] = (unsigned char)(hexv(h[2 * i]) * 16 + hexv(h[2 * i + 1])); return n; }
static void pr(const unsigned char *b, int n) { for (int i = 0; i < n; i++) printf("%02x", b[i]); }
int main(int argc, char **argv)
{
	unsigned char in[64], out[64];
	int len;
	(void)argc;
	memset(out, 0xEE, sizeof out);
	if (argv[1][0] == 'r')
	{
		len = unhex(argv[2], in);
		unsigned char before[64];
		memcpy(before, in, (size_t)len);
		codeplugUtilConvertBufToString((char *)in, (char *)out, len);
		pr(out, len + 1); printf(" "); pr(in, len); printf(" %d\n", memcmp(before, in, (size_t)len) == 0);
	}
	else if (argv[1][0] == 'i')            /* на місці: outBuf == codeplugBuf */
	{
		len = unhex(argv[2], in);
		in[len] = 0xEE;
		codeplugUtilConvertBufToString((char *)in, (char *)in, len);
		pr(in, len + 1); printf("\n");
	}
	else if (argv[1][0] == 'w')
	{
		len = atoi(argv[3]);
		int n = argv[2][0] == '-' ? 0 : unhex(argv[2], in);
		in[n] = 0;
		codeplugUtilConvertStringToBuf((char *)in, (char *)out, len);
		pr(out, len); printf("\n");
	}
	else if (argv[1][0] == 'e')
	{
		unsigned char s[64];
		len = atoi(argv[4]);
		unhex(argv[2], in);
		int n = argv[3][0] == '-' ? 0 : unhex(argv[3], s);
		s[n] = 0;
#if defined(APRS_R21_NAMES)
		printf("%d\n", codeplugUtilNameBufEqualsString((char *)in, (char *)s, len) ? 1 : 0);
#endif
	}
	return 0;
}
"""


def build(variant):
    if variant in HARNESS:
        return HARNESS[variant]
    code = ("#include <stdint.h>\n#include <stdbool.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n" + extract_sources() + MAIN)
    d = tempfile.mkdtemp(prefix="r34_%s_" % variant)
    cpath, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
    open(cpath, "w", encoding="utf-8").write(code)
    r = subprocess.run(["gcc", "-O1", "-Wall", "-Wextra", "-funsigned-char", "-o", exe, cpath] + VARIANTS[variant], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(r.stderr[:2000])
        HARNESS[variant] = None
    else:
        HARNESS[variant] = exe
    return HARNESS[variant]


def run(variant, *args):
    exe = build(variant)
    return subprocess.run([exe] + [str(a) for a in args], capture_output=True, text=True, timeout=20).stdout.split()


def c_read(variant, raw):
    """(рядок результату cp1251-байтами, вхідний буфер після виклику, чи не змінився)."""
    o = run(variant, "r", raw.hex())
    out = bytes.fromhex(o[0])
    assert out[len(raw)] == 0, "завершальний нуль"
    return out[:len(raw)].split(b"\x00", 1)[0], bytes.fromhex(o[1]), o[2] == "1"


def c_write(variant, name_bytes, n=16):
    return bytes.fromhex(run(variant, "w", name_bytes.hex() if name_bytes else "-", n)[0])


NAMES = ["Поляна", "Зоря", "Надія", "Земля", "Ляля", "Земля моя", "Яблуко", "ABC", "Папуга"]


# ----------------------------------------------------------------------------------------------------------------------
#  Z1-Z4: прошивка
# ----------------------------------------------------------------------------------------------------------------------

def test_firmware():
    if subprocess.run(["which", "gcc"], capture_output=True).returncode != 0:
        print("ПРОПУЩЕНО (прошивка): нема gcc")
        return
    for v in VARIANTS:
        check(build(v) is not None, "харнес з реального codeplug.c зібрано: %s" % v)
    # ---------- Z1: читання ----------
    def rd(raw, v="r21"):
        return c_read(v, raw)[0].decode("cp1251")
    check(rd(tail(cp("Поляна"), 0xFF)) == "Поляна", "Z1: «Поляна» (хвіст 0xFF) читається повністю")
    check(rd(tail(cp("Поляна"), 0xFF), "stock") == "Пол", "Z1 (доказ чутливості тесту): СТОКОВИЙ код читає «Поляна» як «Пол»")
    check(rd(tail(cp("Зоря"), 0x00)) == "Зоря", "Z1: «Зоря» з хвостом 0x00 читається повністю")
    check(rd(tail(cp("Надія"), 0x00)) == "Надія", "Z1: «Надія» з хвостом 0x00")
    check(rd(tail(cp("Земля"), 0x00)) == "Земля", "Z1: «Земля» з хвостом 0x00")
    check(rd(tail(cp("Земля моя"), 0x00)) == "Земля моя", "Z1: «Земля моя» -- 0xFF і всередині, і на кінці, хвіст 0x00")
    check(rd(tail(cp("Земля моя"), 0xFF)) == "Земля мо", "Z1: те саме з хвостом 0xFF -- невизначеність формату: кінцеву «я» втрачено (очікувано, не вада коду)")
    check(rd(tail(cp("Зоря"), 0xFF)) == "Зор", "Z1: «Зоря» з хвостом 0xFF -> «Зор» (невизначеність формату)")
    check(rd(tail(cp("Ляля"), 0x00)) == "Ляля" and rd(tail(cp("Яблуко"), 0xFF)) == "Яблуко", "Z1: «Ляля» (00) і «Яблуко» (FF)")
    full = cp("АбвгдежзиклмнопР")
    check(len(full) == 16 and rd(full) == "АбвгдежзиклмнопР", "Z1: назва рівно на 16 байтів без пробілу для хвоста")
    full_ya = cp("Абвгдежзиклмноп") + b"\xff"
    check(rd(full_ya) == "Абвгдежзиклмноп", "Z1: 16 байтів, остання -- «я»: невизначеність, «я» відсікається (CPS таку назву не пише)")
    check(rd(b"\xff" * 16) == "" and rd(b"\x00" * 16) == "", "Z1: порожня назва -- усі 0xFF (як зараз) або всі 0x00")
    check(rd(tail(cp("Папуга"), 0xFF)) == "Папуга", "Z1: звичайна назва")
    gbk = bytes.fromhex("a7b1a7d1a7e1a7e5a7d4a7d1ffffffff")
    check(rd(gbk) == rd(gbk, "stock") and c_read("r21", gbk)[0] == bytes.fromhex("a7b1a7d1a7e1a7e5a7d4a7d1"), "Z4: «Папуга» зі стокової CPS (GBK, хвіст 0xFF, байти з docs/codeplug-encoding.md) читається як раніше")
    # ---------- Z2: вхідний буфер не змінюється ----------
    for nm in NAMES:
        for fill in (0xFF, 0x00):
            raw = tail(cp(nm), fill)
            _s, after, same = c_read("r21", raw)
            check(same and after == raw, "Z2: вхідний буфер після читання «%s» (хвіст %02X) не змінився" % (nm, fill))
    raw = tail(cp("Поляна"), 0xFF)
    _s, after, same = c_read("stock", raw)
    check(not same and 0x00 in after[:6], "Z2 (доказ чутливості): СТОКОВИЙ код псує вхідний буфер (нуль замість 0xFF у «Поляна»)")
    inplace = bytes.fromhex(run("r21", "i", tail(b"AB", 0xFF, 8).hex())[0])
    check(inplace == b"AB" + b"\x00" * 7, "Z2: виклик на місці (позивний, рядки вітання) -- результат у тому ж буфері з нулем в кінці: %s" % inplace.hex())
    inplace2 = bytes.fromhex(run("r21", "i", tail(cp("Зоря"), 0x00, 16).hex())[0])
    check(inplace2[:4] == cp("Зоря") and inplace2[4:] == b"\x00" * 13, "Z2: на місці зберігає кінцеву «я» перед нулями")
    # ---------- Z3: запис -> читання ----------
    names = NAMES + ["", "A", "Гарна назва 15  "[:15]]
    for nm in names:
        b = cp(nm)
        for v in ("r21zt",):
            w = c_write(v, b)
            back = c_read(v, w)[0]
            check(back == b, "Z3 (%s): «%s» -> запис -> читання повертає той самий рядок (запис %s)" % (v, nm, w.hex()))
    # без CODEPLUG_NAME_ZERO_TAIL: назви без «я» наприкінці проходять коло, з «я» наприкінці -- ні (сказано в звіті)
    for nm in names:
        b = cp(nm)
        w = c_write("r21", b)
        back = c_read("r21", w)[0]
        if b.endswith(b"\xff"):
            check(back == b[:-1], "Z3 (r21, ZERO_TAIL вимкнено): «%s» втрачає кінцеву «я» (очікувана межа, CK3)" % nm)
        else:
            check(back == b, "Z3 (r21): «%s» проходить коло" % nm)
    # байт-у-байт стокове там, де «я» наприкінці нема
    same = all(c_write("r21zt", cp(nm)) == c_write("stock", cp(nm)) for nm in names if not cp(nm).endswith(b"\xff"))
    check(same, "Z3: назви без «я» наприкінці пишуться байт-у-байт як у стоковому коді (і порожня -- всі 0xFF)")
    check(c_write("r21zt", b"") == b"\xff" * 16 and c_write("r21", b"") == b"\xff" * 16, "Z3: порожня назва -- усі 0xFF (прошивка вважає запис порожнім за name[0] == 0xFF)")
    check(c_write("r21", cp("Зоря")) == c_write("stock", cp("Зоря")), "Z3: без CODEPLUG_NAME_ZERO_TAIL запис ідентичний стоковому навіть для «Зоря»")
    check(c_write("r21zt", cp("Зоря")) == cp("Зоря") + b"\x00" * 12, "Z3: з CODEPLUG_NAME_ZERO_TAIL «Зоря» -> хвіст 0x00")
    check(c_write("r21zt", cp("Абвгдежзиклмноп") + b"\xff") == cp("Абвгдежзиклмноп") + b"\xff", "Z3: 16 байтів із «я» наприкінці: хвоста нема, лишається як є")
    check(c_write("r21zt", cp("Зоря"), 8) == cp("Зоря") + b"\x00" * 4, "Z3: 8-байтове поле (ім'я рації, APRS) так само")
    # допоміжна функція порівняння
    def eq(buf, s, v="r21"):
        return run(v, "e", buf.hex(), s.hex() if s else "-", 16)[0] == "1"
    check(eq(tail(cp("Зоря"), 0x00), cp("Зоря")) and not eq(tail(cp("Зоря"), 0xFF), cp("Зоря")) and eq(tail(cp("Зоря"), 0xFF), cp("Зор")),
          "Z3: codeplugUtilNameBufEqualsString -- та сама логіка читання")
    check(eq(b"\xff" * 16, b"") and eq(b"\x00" * 16, b""), "Z3: порожня назва дорівнює порожньому рядку")
    # ---------- диференційний тест CPS <-> прошивка на випадкових буферах ----------
    rnd = random.Random(34)
    alphabet = [0xFF, 0x00, 0xFF, 0x00, 0x41, 0x42, 0xE0, 0xA7, 0xF1, 0xD1, 0x20]
    bad_r = bad_w = 0
    for _ in range(400):
        n = rnd.choice((8, 16))
        raw = bytes(rnd.choice(alphabet) for _ in range(n))
        if c_read("r21", raw)[0] != cv.name_bytes(raw):
            bad_r += 1
            if bad_r <= 3:
                print("   розбіжність читання:", raw.hex(), c_read("r21", raw)[0].hex(), cv.name_bytes(raw).hex())
        s = bytes(rnd.choice([0x41, 0xE0, 0xFF, 0x20]) for _ in range(rnd.randint(0, n)))
        if s and s[0] == 0xFF and False:
            continue
        if c_write("r21zt", s, n) != cv.pad_name(s, n):
            bad_w += 1
            if bad_w <= 3:
                print("   розбіжність запису:", s.hex(), n, c_write("r21zt", s, n).hex(), cv.pad_name(s, n).hex())
    check(bad_r == 0, "Z5: codeplug_view.name_bytes == код прошивки на 400 випадкових буферах (розбіжностей: %d)" % bad_r)
    check(bad_w == 0, "Z5: codeplug_view.pad_name == код прошивки з CODEPLUG_NAME_ZERO_TAIL на 400 випадкових назвах (розбіжностей: %d)" % bad_w)


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: CPS на кодплазі-фікстурі
# ----------------------------------------------------------------------------------------------------------------------

def test_tools():
    # правила читання/запису
    check(cv.name_bytes(tail(cp("Поляна"), 0xFF)) == cp("Поляна"), "Z5: name_bytes -- «Поляна»")
    check(cv.name_bytes(tail(cp("Зоря"), 0x00)) == cp("Зоря"), "Z5: name_bytes -- «Зоря» з хвостом 0x00")
    check(cv.decode_name_ex(tail(cp("Надія"), 0x00)) == ("Надія", "cp1251"), "Z5: decode_name_ex -- «Надія»: %r" % (cv.decode_name_ex(tail(cp("Надія"), 0x00)),))
    check(cv.decode_name_ex(bytes.fromhex("a7b1a7d1a7e1a7e5a7d4a7d1ffffffff"))[0] == "Папуга", "Z5/Z4: GBK «Папуга» зі стокової CPS читається як раніше")
    check(cv.pad_name(cp("Надія")) == cp("Надія") + b"\x00" * 11 and cv.pad_name(b"ABC") == b"ABC" + b"\xff" * 13 and cv.pad_name(b"") == b"\xff" * 16,
          "Z5: pad_name: «я» наприкінці -> 0x00, решта -> 0xFF, порожня -> усе 0xFF")
    check(cv.pad_name(b"AB", 8, b"\x00") == b"AB" + b"\x00" * 6, "Z5: pad_name з fill=0x00 (APRS) не змінює поведінки")
    # перевірка назви для вікна
    for nm in ("Надія", "Країна моя", "Поляна", "Зоря"):
        c = ce.check_name(nm)
        check(c["ok"], "Z5: check_name приймає «%s»: %s" % (nm, c["message"]))
    c = ce.check_name("Надія")
    check(c["warning"] and "0x00" in c["message"] and "CODEPLUG_NAME_ZERO_TAIL" in c["message"], "N4.2: для назви на «я» (cp1251) є попередження, що саме й чому: %s" % c["message"])
    check(not ce.check_name("Поляна")["warning"], "N4.2: «Поляна» (GBK, без 0xFF) -- без попередження")
    c = ce.check_name("Україна моя і твоя")                           # 16 байтів, cp1251, закінчується на «я»
    t16 = "Абвгдежзиклмнопя"                                         # 16 символів cp1251? GB2312 прийме «Абв...» -- беремо українську літеру для cp1251
    t16 = "Іабвгдежзиклмноя"
    raw16 = cc.encode_new_name(t16)[0]
    c = ce.check_name(t16)
    check(len(raw16) == 16 and raw16[-1] == 0xFF and not c["ok"] and "скоротіть" in c["message"], "N4.2: 16 байтів, кінцева «я» -- відмова з порадою (хвоста нема): %s" % c["message"])
    c = ce.check_name("яблуко")
    raw = cc.encode_new_name("яблуко")[0]
    check(raw[0] != 0xFF or not c["ok"], "Z5: назва з малої «я» (cp1251) для контакту відхиляється: %s" % c["message"])
    c = ce.check_name("Їжак я")
    ci = ce.check_name("яЇжак")
    check(not ci["ok"] and "починатися" in ci["message"], "Z5: «яЇжак» (cp1251, перший байт 0xFF) відхилено: %s" % ci["message"])
    check(ce.check_name("яЇжак", first_ff_empty=False)["ok"], "Z5: для каналів/зон/списків перший байт 0xFF дозволено (там порожність за бітовою маскою)")
    # фікстура: додати/прочитати/CSV
    import test_cps_csv as tc
    from cps_ui import document as D
    spi = tc.make_fixture_spi()
    cpl, _data = tc.codeplug_of(spi)
    doc = D.Document(cpl, D.ORIGIN_FILE, source_file="фікстура.zip")
    DP = ","
    for nm in ("Надія", "Світлана Земля"[:14], "Країна моя"):
        doc.apply(te.contact_add(doc.image, nm, 777, 0, DP))
    rows = {r[1]: r for r in te.contact_rows(doc.image)}
    check("Надія" in rows and "Країна моя" in rows, "Z5: контакти «Надія» і «Країна моя» додано й прочитано повністю: %s" % sorted(rows))
    recs = dict(doc.image.contacts())
    raw = recs[rows["Надія"][0]][:16]
    check(raw == cp("Надія") + b"\x00" * 11, "Z5: «Надія» лежить у кодплазі з хвостом 0x00: %s" % raw.hex())
    raw2 = recs[rows["Країна моя"][0]][:16]
    check(raw2 == cp("Країна моя") + b"\x00" * 6, "Z5: «Країна моя» -- так само: %s" % raw2.hex())
    # CSV: туди й назад без змін
    exp = cc.export_rows(doc.image, DP)
    names = [r[0] for r in exp["contacts"][1]]
    check(any(n.endswith("\xff") for n in names), "Z5: у CSV (сумісна колонка, Latin-1) назва на «я» закінчується символом ÿ (0xFF)")
    tabs = {k: cc.Table(cc.FILE_NAMES[k], list(h), [(i + 2, list(r)) for i, r in enumerate(rws)]) for k, (h, rws) in exp.items()}
    res = cc.import_csv(doc.image, tabs, DP, cc.Session(numeric_refs=True))
    check(bytes(res.image.eeprom) == bytes(doc.image.eeprom) and bytes(res.image.flash) == bytes(doc.image.flash), "Z5: експорт у CSV й імпорт назад байт-у-байт не змінює кодплаг (назви з «я»)")
    # нова назва лише в читабельній колонці
    hdr, rws = te.tables_of(doc.image, DP)["contacts"]
    rws.append(["", "888", "Group", "Disabled", "Наш Дім і Надія"])
    res = te._run(doc.image, {"contacts": (hdr, rws)}, DP)
    got = {r[1]: r for r in te.contact_rows(res.image)}
    check("Наш Дім і Надія" in got, "Z5: імпорт читабельної назви на «я» -- записано й прочитано: %s" % sorted(got))
    # перейменування, дублювання, видалення «Надія»
    doc.apply(te.rename_entity(doc.image, "contact", rows["Надія"][0], "Зоря моя", DP))
    check(any(r[1] == "Зоря моя" for r in te.contact_rows(doc.image)), "Z5: перейменування на назву з «я» наприкінці")
    try:
        te.contact_add(doc.image, "яЇжак", 5, 0, DP)
        check(False, "Z5: назва з першим байтом 0xFF мала бути відхилена в редакторі")
    except te.TableEditError as e:
        check("починатися" in "\n".join(e.problems), "Z5: відмова зі словами: %s" % e.problems)
    # name_problem (вікно редактора): перша «я» у контактах/DTMF -- відмова (запис вважається порожнім за name[0]==0xFF), у каналах -- дозволено
    for kd in ("contact", "dtmf"):
        pr = te.name_problem(doc.image, kd, "яЇжак")
        check(pr and "починатися" in pr, "Z5: name_problem(%s, «яЇжак») відмовляє: %r" % (kd, pr))
    pr = te.name_problem(doc.image, "channel", "яЇжак")
    check(pr is None, "Z5: name_problem(channel, «яЇжак») дозволяє: %r" % pr)
    # імпорт CSV: перша «я» у контактах -> відмова, у каналах -> дозволено
    hdr, rws = te.tables_of(doc.image, DP)["contacts"]
    rws.append(["", "999", "Group", "Disabled", "яЇжак"])
    try:
        te._run(doc.image, {"contacts": (hdr, rws)}, DP)
        check(False, "Z5: CSV: контакт «яЇжак» мав бути відхилений")
    except te.TableEditError as e:
        check("починатися" in "\n".join(e.problems), "Z5: CSV відхиляє контакт з першою «я»: %s" % e.problems)
    # назва каналу, що закінчується на «я» з Ukrainian-літерою
    chn = te.channels(doc.image, DP)
    if chn:
        num = chn[0][0]
        res = te.rename_entity(doc.image, "channel", num, "Київська моя", DP)
        nm = dict(te.entity_names(res.image, "channel"))[num]
        check(nm == "Київська моя", "Z5: канал «Київська моя» (cp1251, «я» наприкінці): %r" % nm)


def main():
    for fn in (test_firmware, test_tools):
        n0 = len(FAILS)
        try:
            fn()
        except Exception as e:      # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (fn.__name__, e))
        print("%s %s" % ("OK  " if len(FAILS) == n0 else "FAIL", fn.__name__))
    if FAILS:
        print("\nПровалів: %d" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        return 1
    print("\nR34: усе гаразд")
    return 0


if __name__ == "__main__":
    sys.exit(main())
