#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX2 (хост): «Подвійний прийом» -- конверти за джерелом (біт 31 peerId), картка (тони, відстань), AES при перенастроюванні, правки A, шрифти, підказка літер.
  Д  біт 31 peerId: СПРАВЖНІЙ dmr_sms.c (tests/test_dmr_sms_peerb.c) + мутанти; аудит читачів peerId; uiChannelModeDualOnCardB, uiUnreadCountCard (справжні функції);
     лічильників у RAM нема; геометрія індикаторів (D + APRS одночасно, без накладань, координати з констант)
  К  К1 відстань на активній картці (справжня функція), К2 тони RX/TX у рядку 3 FM (справжні функції, таблиця прикладів)
  Е  скидання RX AES при перенастроюванні (tests/test_aes_retune.c + мутант); усі перенастроювання йдуть через dualTune
  Є  правки каналу A при заході на B: справжній dualTune (модель буферів) + мутанти
  Ж  кирилиця й шрифти без гліфів (дані шрифту з HX8353E_charset_UA.h)
  Л  підказка літер при наборі назви каналу: справжня відмальовка (вікно у межах екрана) + статика
Запуск: python3 tools/test_r98fix2.py"""
import os, re, subprocess, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa  (pp, carve_fn, rd, APP, FW)
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
FN = os.path.join(APP, "source", "functions")
INC = os.path.join(APP, "include")
BASE = "11fa133"   # коміт бази R98-FIX2 (HEAD після R98-FIX1)


def base_available():
    return subprocess.run(["git", "cat-file", "-e", BASE + "^{commit}"], cwd=FW, capture_output=True).returncode == 0


def base_file(rel):
    r = subprocess.run(["git", "show", "%s:MDUV380_firmware/%s" % (BASE, rel)], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def run_in(code, extra=()):
    d = tempfile.mkdtemp(prefix="r98f2_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-I", INC] + list(extra) + ["-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:2500]); return None
        return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def kv(out):
    return dict(l.split("=", 1) for l in (out or "").splitlines() if "=" in l)


# ---------------------------------------------------------------------------------------- збірка справжнього dmr_sms.c (peerb) з можливою мутацією
FW_INCS = ["-I" + os.path.join(FW, "tools", "hoststub"), "-include", os.path.join(FW, "tools", "hoststub", "host_compat.h"), "-I" + FW, "-I" + os.path.join(FW, "Core", "Inc"),
           "-I" + os.path.join(FW, "Drivers/CMSIS/Device/ST/STM32F4xx/Include"), "-I" + os.path.join(FW, "Drivers/CMSIS/Include"),
           "-I" + os.path.join(FW, "Drivers/STM32F4xx_HAL_Driver/Inc"), "-I" + os.path.join(FW, "Drivers/STM32F4xx_HAL_Driver/Inc/Legacy"),
           "-I" + os.path.join(FW, "Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc"), "-I" + os.path.join(FW, "Middlewares/ST/STM32_USB_Device_Library/Core/Inc"),
           "-I" + os.path.join(FW, "Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2"), "-I" + os.path.join(FW, "Middlewares/Third_Party/FreeRTOS/Source/include"),
           "-I" + os.path.join(FW, "Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F"), "-I" + os.path.join(FW, "USB_DEVICE/App"), "-I" + os.path.join(FW, "USB_DEVICE/Target"),
           "-I" + INC]
PEERB_FLAGS = FW_INCS + ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_DUAL_CHANNEL",
                         "-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_CALL_REPLAY", "-I" + os.path.join(INC, "crypto"), "-std=gnu11", "-O1", "-w"]


def build_peerb(sms_src_text):
    """Збирає tests/test_dmr_sms_peerb.c з (можливо мутованим) dmr_sms.c; повертає (код виходу, вивід)."""
    d = tempfile.mkdtemp(prefix="r98f2p_")
    try:
        sms = os.path.join(d, "dmr_sms.c"); open(sms, "w", encoding="utf-8").write(sms_src_text)
        srcs = [os.path.join(FW, "tests", "test_dmr_sms_peerb.c"), sms, os.path.join(FN, "dmr_sms_fix.c"), os.path.join(FN, "dmr_sms_pdu.c"),
                os.path.join(APP, "source", "crypto", "dmr_aes.c"), os.path.join(FN, "dmr_sms_text.c")]
        exe = os.path.join(d, "t")
        r = subprocess.run(["gcc"] + PEERB_FLAGS + srcs + ["-o", exe], capture_output=True)
        if r.returncode != 0:
            return (-1, r.stderr.decode()[:1500])
        p = subprocess.run([exe], capture_output=True)
        return (p.returncode, p.stdout.decode())
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ Д
ONB_HARNESS = r'''
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
static int en, onB, same;
static bool dcIsEnabled(void) { return en; }
static bool dcIsOnB(void) { return onB; }
static bool dualBSameAsA(void) { return same; }
@@FN@@
int main(void)
{
	int r[4];
	en = 1; onB = 0; same = 0; r[0] = uiChannelModeDualOnCardB();   /* на A */
	onB = 1; r[1] = uiChannelModeDualOnCardB();                      /* на B */
	same = 1; r[2] = uiChannelModeDualOnCardB();                     /* A == B -> A */
	same = 0; en = 0; r[3] = uiChannelModeDualOnCardB();             /* режим вимкнено */
	printf("r=%d%d%d%d\n", r[0], r[1], r[2], r[3]);
	return 0;
}
'''

CARD_HARNESS = r'''
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
static int total, onb;
static int dmrSmsUnreadCount(void) { return total; }
static int dmrSmsUnreadCountB(void) { return onb; }
@@FN@@
int main(void)
{
	int cases[][2] = { {0,0}, {3,0}, {3,1}, {3,3}, {2,5}, {-1,0}, {5,2} };
	for (int i = 0; i < 7; i++) { total = cases[i][0]; onb = cases[i][1]; printf("c%d=%u,%u\n", i, uiUnreadCountCard(0), uiUnreadCountCard(1)); }
	return 0;
}
'''


def eval_const(src, name, env=None):
    env = dict(env or {})
    for m in re.finditer(r"^#define\s+(\w+)\s+(.*?)\s*(?://.*)?$", src, re.M):
        env.setdefault(m.group(1), m.group(2).strip())
    s = env[name]
    for _ in range(10):
        s2 = re.sub(r"\b[A-Za-z_]\w*\b", lambda mm: ("(" + env[mm.group(0)] + ")") if mm.group(0) in env else mm.group(0), s)
        if s2 == s:
            break
        s = s2
    return int(eval(s.replace("/", "//")))


def rects_overlap(a, b):
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def test_part_d(incs, cf):
    sms = T.rd(os.path.join(FN, "dmr_sms.c"))
    # --- СПРАВЖНІЙ dmr_sms.c + мутанти (tests/test_dmr_sms_peerb.c)
    rc, out = build_peerb(sms)
    check(rc == 0 and "ПРОЙДЕНО" in out, "Д: справжній dmr_sms.c: біт 31, чистий ID, рахунки B, читання/видалення/перенумерація (tests/test_dmr_sms_peerb.c): %s" % (out[-300:] if rc != 0 else "ok"))
    muts = (
        ("біт картки не ставиться", "if (uiChannelModeDualOnCardB()) { peerStore |= DMR_SMS_PEER_ON_B; }", "if (0) { peerStore |= DMR_SMS_PEER_ON_B; }"),
        ("біт у відкладене вхідне не передається", "s_pendInboxPeer = SMS_STORE_PEER;", "s_pendInboxPeer = peer;"),
        ("dmrSmsGet без маски", "s_scratch.peerId  = SMS_PEER_CLEAN((uint32_t)s_store.data[o + 4]", "s_scratch.peerId  = ((uint32_t)s_store.data[o + 4]"),
        ("NewestInbox без маски", "s_scratch.peerId  = SMS_PEER_CLEAN(s_pendInboxPeer);", "s_scratch.peerId  = s_pendInboxPeer;"),
        ("рахунок B не за бітом", "(s_store.data[o + 7] & 0x80))", "1)"),
        ("біт на «Надісланих»", "s_store.data[o + 7] = (uint8_t)((peerId >> 24) & 0xFF);", "s_store.data[o + 7] = (uint8_t)(((peerId >> 24) & 0xFF) | ((flags & DMR_SMS_FLAG_OUTGOING) ? 0x80 : 0));"),
        ("маска лише біт 31 (залишає старші байти)", "#define dmrSmsPeerClean(p)     ((uint32_t)(p) & DMR_SMS_PEER_ID_MASK)", "#define dmrSmsPeerClean(p)     ((uint32_t)(p) & 0x7FFFFFFFu)"),
    )
    for what, old, new in muts:
        if old not in sms and old not in T.rd(os.path.join(INC, "functions", "dmr_sms.h")):
            check(False, "Д (мутант): фрагмент не знайдено: %s" % what); continue
        if old in sms:
            rc2, out2 = build_peerb(sms.replace(old, new, 1))
            check(rc2 != 0 or "ПРОЙДЕНО" not in out2, "Д (мутант): %s -- ловиться" % what)
    # мутант у заголовку (маска): збираємо з копією заголовка
    hdr = T.rd(os.path.join(INC, "functions", "dmr_sms.h"))
    mh = hdr.replace("#define dmrSmsPeerClean(p)     ((uint32_t)(p) & DMR_SMS_PEER_ID_MASK)", "#define dmrSmsPeerClean(p)     ((uint32_t)(p) & 0x7FFFFFFFu)")
    if mh != hdr:
        d = tempfile.mkdtemp(prefix="r98f2h_")
        try:
            os.makedirs(os.path.join(d, "functions"))
            open(os.path.join(d, "functions", "dmr_sms.h"), "w", encoding="utf-8").write(mh)
            d2 = tempfile.mkdtemp(prefix="r98f2p2_")
            srcs = [os.path.join(FW, "tests", "test_dmr_sms_peerb.c"), os.path.join(FN, "dmr_sms.c"), os.path.join(FN, "dmr_sms_fix.c"), os.path.join(FN, "dmr_sms_pdu.c"),
                    os.path.join(APP, "source", "crypto", "dmr_aes.c"), os.path.join(FN, "dmr_sms_text.c")]
            r = subprocess.run(["gcc", "-I" + d] + PEERB_FLAGS + srcs + ["-o", os.path.join(d2, "t")], capture_output=True)
            ok = (r.returncode != 0)
            if r.returncode == 0:
                p = subprocess.run([os.path.join(d2, "t")], capture_output=True)
                ok = (p.returncode != 0)
            shutil.rmtree(d2, ignore_errors=True)
            check(ok, "Д (мутант): маска лише біт 31 (старший байт-сміття потрапляє в ID) -- ловиться")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    # --- аудит читачів peerId: сире слово зі сховища читається ЛИШЕ в dmrSmsGet (з маскою) і в рахунку B; інші модулі бачать лише чистий ID
    raw_reads = [m.start() for m in re.finditer(r"s_store\.data\[o \+ [4567]\]", sms)]
    lines = sorted(set(sms.count("\n", 0, p) + 1 for p in raw_reads))
    check(len(raw_reads) >= 5, "Д аудит: сирі байти peer у dmr_sms.c знайдено (%s)" % lines)
    gi = sms.find("const dmrSmsMessage_t *dmrSmsGet(int outgoing, int idx)")
    gend = sms.find("\n}\n", gi)
    inside_get = [p for p in raw_reads if gi < p < gend]
    ci = sms.find("int dmrSmsUnreadCountB(void)"); cend = sms.find("\n}\n", ci)
    inside_cnt = [p for p in raw_reads if ci < p < cend]
    si = sms.find("static void store_add("); send = sms.find("\n}\n", si)
    inside_add = [p for p in raw_reads if si < p < send]
    check(len(inside_get) + len(inside_cnt) + len(inside_add) == len(raw_reads), "Д аудит: сирі байти peer читаються/пишуться лише у dmrSmsGet, dmrSmsUnreadCountB, store_add")
    check("SMS_PEER_CLEAN(" in sms[gi:gend], "Д аудит: dmrSmsGet() знімає біт картки")
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\n#define SMS_PEER_CLEAN\(p\)\s+dmrSmsPeerClean\(p\)\n#define SMS_STORE_PEER\s+peerStore\n#else\n#define SMS_PEER_CLEAN\(p\)\s+p\n#define SMS_STORE_PEER\s+peer\n#endif", sms) is not None, "Д: з режимом -- маска/біт, без режиму макроси дають текст як до R98-FIX2")
    check("SMS_PEER_CLEAN(s_pendInboxPeer)" in sms, "Д аудит: dmrSmsNewestInbox() (відкладене вхідне) знімає біт картки")
    others = []
    for root, _, files in os.walk(os.path.join(APP, "source")):
        for f in files:
            if f.endswith(".c"):
                p = os.path.join(root, f)
                if os.path.basename(p) == "dmr_sms.c": continue
                t = T.rd(p)
                for m in re.finditer(r"(\w+)\s*(?:->|\.)\s*peerId\b", t):
                    others.append((os.path.relpath(p, APP), m.group(1)))
    names = sorted(set(n for _, n in others))
    check(all(n == "m" for n in names) and len(others) == 3, "Д аудит: поле peerId читають лише 3 місця (uiNotification, menuMessages x2) через m = dmrSmsGet()/dmrSmsNewestInbox() -- чисті: %s" % others)
    for rel in ("source/user_interface/menuMessages.c", "source/user_interface/uiNotification.c"):
        t = T.rd(os.path.join(APP, rel))
        check(("dmrSmsGet(" in t) or ("dmrSmsNewestInbox(" in t), "Д аудит: %s отримує m лише від dmrSmsGet/dmrSmsNewestInbox" % rel)
    # python-інструменти й USB: сховище SMS не розбирають (peer лише з PDU діагностики)
    pyd = os.path.join(FW, "tools")
    bad = []
    for f in os.listdir(pyd):
        if f.endswith(".py") and f not in ("test_r98fix2.py",):
            t = T.rd(os.path.join(pyd, f))
            if "MSGV" in t or "SMS_ENTRY_HDR" in t:
                bad.append(f)
    check(not bad, "Д аудит: жоден python-інструмент не розбирає запис сховища SMS (MSGV): %s" % bad)
    usb = T.rd(os.path.join(APP, "source", "usb", "usb_com.c"))
    check("dmrSmsGet(" not in usb and "dmrSmsNewestInbox(" not in usb, "Д аудит: USB-команди не читають записи сховища")
    # --- довжина/формат запису не змінені: заголовок запису лишається 12 Б, store_add пише ті самі 4 байти peer
    check("#define SMS_ENTRY_HDR" in sms and re.search(r"#define SMS_ENTRY_HDR\s+12", sms) is not None, "Д: довжина заголовка запису (12 Б) не змінена")
    # --- uiChannelModeDualOnCardB (справжня)
    tc = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = T.carve_fn(tc or "", "_Bool uiChannelModeDualOnCardB(void)")
    check(fn is not None, "Д: uiChannelModeDualOnCardB знайдено")
    if fn:
        out = run_in(ONB_HARNESS.replace("@@FN@@", fn))
        check((out or "").strip() == "r=0100", "Д: біт лише при ввімкненому режимі на B (A -> 0, B -> 1, A==B -> 0, режим вимкнено -> 0): %s" % (out or "").strip())
        for what, m in (("без перевірки A==B", fn.replace("&& (dualBSameAsA() == 0)", "")), ("без перевірки «режим ввімкнено»", fn.replace("dcIsEnabled() &&", "1 &&"))):
            mo = run_in(ONB_HARNESS.replace("@@FN@@", m)) if m != fn else None
            check(m != fn and mo is not None and mo != out, "Д (мутант): %s -- ловиться" % what)
    # --- uiUnreadCountCard (справжня)
    tu = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiUtilities.c")
    fn = T.carve_fn(tu or "", "unsigned uiUnreadCountCard(_Bool cardB)")
    check(fn is not None, "Д: uiUnreadCountCard знайдено")
    if fn:
        out = run_in(CARD_HARNESS.replace("@@FN@@", fn))
        o = kv(out)
        exp = {"c0": "0,0", "c1": "3,0", "c2": "2,1", "c3": "0,3", "c4": "0,2", "c5": "0,0", "c6": "3,2"}
        check(all(o.get(k) == v for k, v in exp.items()), "Д: картка A = усього - B, картка B = за бітом (B > усього -> clamp): %s" % o)
        m = fn.replace("(cardB ? onB : (total - onB))", "(cardB ? onB : total)")
        mo = run_in(CARD_HARNESS.replace("@@FN@@", m)) if m != fn else None
        check(m != fn and mo is not None and mo != out, "Д (мутант): A не віднімає B -- ловиться")
        check("dmrSmsUnreadCount()" in fn and "dmrSmsUnreadCountB()" in fn, "Д: рахунок -- через dmrSmsUnreadCount/dmrSmsUnreadCountB, не дублює прохід")
    # --- лічильників у RAM нема
    allsrc = ""
    for root, _, files in os.walk(APP):
        for f in files:
            if f.endswith((".c", ".h")) and "languages" not in root:
                allsrc += T.rd(os.path.join(root, f), "latin-1")
    for tok in ("s_dcUnread", "dcUnreadNote", "dcUnreadCards", "dcUnreadCountsNote", "dcUnreadCountsSplit", "uiChannelModeDualSmsReceived"):
        check(tok not in allsrc, "Д2: «%s» прибрано (лічильників у RAM нема)" % tok)
    dcc = T.rd(os.path.join(FN, "dual_channel.c"))
    check(not re.findall(r"^static [a-z_0-9]+ ([a-zA-Z_0-9]+)\[", dcc, re.M), "Д2: у dual_channel.c нових масивів нема")
    # --- Д3: індикатори на картці
    ucm = T.rd(os.path.join(UI, "uiChannelMode.c"))
    env = {}
    for m in re.finditer(r"^#define\s+(DW_\w+)\s+(.*?)\s*(?://.*)?$", ucm, re.M):
        env[m.group(1)] = m.group(2).strip()
    env["DISPLAY_Y_POS_BAR"] = "10"

    def C(n):
        return eval_const(ucm, n, env)
    if "DW_SQ_X" not in env:
        print("ПРОПУСК: Д3 -- розкладку карток (квадрат 24x51, «D» у квадраті) замінено в R98-FIX5 Б2; координати й накладання перевіряє tools/test_r98fix5.py")
        return
    DISP_X = 160
    card = (0, 0, C("DW_CARD_X") + C("DW_CARD_W") + 1, C("DW_CARD_H"))
    r = {
        "квадрат A/B": (C("DW_SQ_X"), C("DW_SQ_DY"), C("DW_SQ_W"), C("DW_SQ_H")),
        "літера A/B": (C("DW_LETTER_X"), C("DW_LETTER_DY"), 16, 32),
        "▸": (C("DW_SQ_X") + C("DW_SQ_W") // 2 - 2, C("DW_ARROW_DY"), 5, 5),
        "D: літера+конверт+число": (C("DW_UN_LETTER_X"), C("DW_UN_DY"), C("DW_UN_NUM_X") + 6 - C("DW_UN_LETTER_X"), 8),
        "APRS A: бокс": (C("DW_AP_X"), C("DW_AP_DY"), C("DW_AP_W"), C("DW_AP_H")),
        "рядок 1": (C("DW_TXT_X"), C("DW_LINE1_DY"), C("DW_L1_MAX_AP") * 6, 8),
        "рядок 2": (C("DW_TXT_X"), C("DW_LINE2_DY"), 16 * 8, 16),
        "рядок 3": (C("DW_TXT_X"), C("DW_LINE3_DY"), C("DW_LINE3_MAX") * 6, 8),
        "замок AES": (C("DW_LOCK_X"), C("DW_LOCK_DY"), 10, 9),
        "смуга активності": (C("DW_TXT_X"), C("DW_METER_DY"), C("DW_METER_X") + C("DW_METER_SEGS") * C("DW_METER_STEP") - 2 - C("DW_TXT_X"), C("DW_METER_H")),
    }
    # D -- у межах квадрата; решта -- між собою без накладань (квадрат містить літеру, ▸ і D навмисно)
    sq = r["квадрат A/B"]
    inside = lambda a, b: a[0] >= b[0] and a[1] >= b[1] and a[0] + a[2] <= b[0] + b[2] and a[1] + a[3] <= b[1] + b[3]
    check(inside(r["D: літера+конверт+число"], sq) and inside(r["літера A/B"], sq) and inside(r["▸"], sq), "Д3: літера, ▸ і індикатор «D» -- у квадраті картки: %s" % (r["D: літера+конверт+число"],))
    pairs_inner = [("літера A/B", "▸"), ("літера A/B", "D: літера+конверт+число"), ("▸", "D: літера+конверт+число")]
    for a, b in pairs_inner:
        check(not rects_overlap(r[a], r[b]), "Д3: у квадраті «%s» і «%s» не накладаються" % (a, b))
    outer = [k for k in r if k not in ("літера A/B", "▸", "D: літера+конверт+число")]
    for i in range(len(outer)):
        for j in range(i + 1, len(outer)):
            a, b = outer[i], outer[j]
            check(not rects_overlap(r[a], r[b]), "Д3: «%s» і «%s» не накладаються: %s %s" % (a, b, r[a], r[b]))
    for k, v in r.items():
        check(v[0] >= 0 and v[0] + v[2] <= C("DW_CARD_X") + C("DW_CARD_W") and v[1] >= 0 and v[1] + v[3] <= C("DW_CARD_H"), "Д3: «%s» у межах картки: %s" % (k, v))
    # APRS і D -- одночасно, APRS не залежить від D
    row = ucm[ucm.find("static void dualRenderRow("):]
    row = row[:row.find("\n}\n")]
    check("unsigned aprsUn = (isB ? uiUnreadCount('A') : 0U);" in row and "unsigned un = uiUnreadCountCard(isB);" in row, "Д3: «D» (uiUnreadCountCard) і APRS «A» (uiUnreadCount('A')) обчислюються незалежно")
    check(not re.search(r"if\s*\(isB\s*&&\s*\(un\s*==\s*0", row), "Д3: APRS не ховається, коли є «D» (немає умови «un == 0»)")
    ai = row.find("if (aprsUn > 0U)\n\t{\n\t\tchar ap[3];")
    check(ai > 0 and "if (un > 0U)" not in row[ai - 120:ai], "Д3: маркер APRS малюється за власною умовою aprsUn > 0")
    check("l1[DW_L1_MAX_AP] = 0;" in row and row.find("l1[DW_L1_MAX_AP] = 0;") < row.find("displayPrintCore(DW_TXT_X, (y + DW_LINE1_DY), l1"), "Д3: рядок 1 скорочується до 18 символів лише коли є маркер APRS (до виводу)")
    # мутант: APRS знову «лише коли нема D»
    mutrow = row.replace("unsigned aprsUn = (isB ? uiUnreadCount('A') : 0U);", "unsigned aprsUn = (isB ? uiUnreadCount('A') : 0U);\n\tif (isB && (uiUnreadCountCard(isB) > 0U)) { aprsUn = 0U; }")
    check(mutrow != row and not re.search(r"aprsUn\s*=\s*0U;\s*\}", row), "Д3 (мутант): приховування APRS при наявності «D» -- ловиться статичною перевіркою")


# ------------------------------------------------------------------------------------------------ К
TONE_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
typedef enum { CSS_TYPE_NONE = 1, CSS_TYPE_CTCSS = 2, CSS_TYPE_DCS = 0x8000, CSS_TYPE_DCS_INVERTED = 0x4000, CSS_TYPE_DCS_MASK = 0xC000 } CodeplugCSSTypes_t;
static CodeplugCSSTypes_t codeplugGetCSSType(uint16_t tone)
{
	if ((tone == 0xFFFF) || (tone == 0)) return CSS_TYPE_NONE;
	if ((tone & CSS_TYPE_DCS_MASK) == 0) return CSS_TYPE_CTCSS;
	if (tone & CSS_TYPE_DCS_INVERTED) return (CodeplugCSSTypes_t)(CSS_TYPE_DCS | CSS_TYPE_DCS_INVERTED);
	return CSS_TYPE_DCS;
}
static size_t dcsPrintf(char *dest, size_t maxLen, char *prefix, uint16_t tone)
{
	return snprintf(dest, maxLen, "%sD%03X%c", (prefix ? prefix : ""), (tone & ~CSS_TYPE_DCS_MASK), ((tone & CSS_TYPE_DCS_INVERTED) ? 'I' : 'N'));
}
@@FN1@@
@@FN2@@
static void show(uint16_t rx, uint16_t tx, int bw)
{
	char l3[20]; dualFmToneLine(l3, sizeof l3, rx, tx, bw);
	printf("%04X/%04X/%d=%s|%d\n", rx, tx, bw, l3, (int)strlen(l3));
}
int main(void)
{
	show(670, 670, 1);                 /* однакові CTCSS */
	show(670, 885, 1);                 /* різні CTCSS */
	show(670, 0xFFFF, 1);              /* лише RX */
	show(0xFFFF, 885, 0);              /* лише TX, 12.5k */
	show(0xFFFF, 0xFFFF, 1);           /* без тонів */
	show(0, 0, 0);                     /* 0 = нема тону */
	show(0x8000 | 0x023, 0x8000 | 0x023, 1);        /* однакові DCS (N) */
	show(0x8000 | 0x023, 0xC000 | 0x754, 0);        /* різні DCS (N/I), 12.5k -- найдовший DCS */
	show(0x8000 | 0x023, 670, 1);                   /* DCS RX + CTCSS TX */
	show(2541, 2541, 0);                            /* 254.1 Гц */
	show(2541, 2500, 0);                            /* найдовший CTCSS: «R254.1 T250.0 12.5k» */
	show(0xC000 | 0x754, 2541, 0);                  /* DCS-I + CTCSS, 12.5k */
	return 0;
}
'''

DIST_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#define LC_DIST_LABEL_SIZE 16
#define DW_LINE3_MAX 19
typedef struct { double locationLat, locationLon; } LinkItem_t;
static LinkItem_t item; static LinkItem_t *LinkHead = &item;
static int own, labelOk; static const char *labelTxt = "123m";
static bool settingsLocationIsValid(void) { return own; }
static double settingsLocationGetLatitude(void) { return 50.0; }
static double settingsLocationGetLongitude(void) { return 30.0; }
static bool lcDistLabel(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon, uint16_t *bearingDeg, bool *bearingKnown)
{
	(void)ownPositionValid; (void)myLat; (void)myLon; (void)lat; (void)lon;
	if (!labelOk) return false;
	snprintf(buf, size, "%s", labelTxt); *bearingDeg = 0; *bearingKnown = true; return true;
}
@@FN@@
static void go(const char *n, const char *base, int o, double lat, int lok, const char *lab)
{
	char l3[DW_LINE3_MAX + 1]; snprintf(l3, sizeof l3, "%s", base);
	own = o; item.locationLat = lat; labelOk = lok; labelTxt = lab;
	dualAppendDistance(l3); printf("%s=%s\n", n, l3);
}
int main(void)
{
	go("ok", "TS1 CC1 TG91", 1, 50.1, 1, "123m");                 /* придатна: додається */
	go("km", "TS1 CC1 TG91", 1, 50.1, 1, "532km");                /* кілометри */
	go("noown", "TS1 CC1 TG91", 0, 50.1, 1, "123m");             /* своєї позиції нема */
	go("nocoord", "TS1 CC1 TG91", 1, 1000.0, 1, "123m");         /* координат у цьому виклику не прийнято (locationLat > 90) */
	go("bad", "TS1 CC1 TG91", 1, 50.1, 0, "123m");               /* пара непридатна ((0,0), діапазон) */
	go("full", "TS1 CC1 TG 1234567", 1, 50.1, 1, "12km");        /* не влізає -- не додається */
	go("exact", "TS1 CC1 TG 123", 1, 50.1, 1, "123m");         /* рівно 19 символів -- влізає */
	return 0;
}
'''


def test_part_k(incs, cf):
    tc = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    f1 = T.carve_fn(tc or "", "size_t dualToneOne(char *dst, size_t size, const char *mark, uint16_t tone)")
    f2 = T.carve_fn(tc or "", "void dualFmToneLine(char *l3, size_t size, uint16_t rxTone, uint16_t txTone, _Bool bw25)")
    check(f1 is not None and f2 is not None, "К2: функції тонів знайдено")
    table = {}
    if f1 and f2:
        out = run_in(TONE_HARNESS.replace("@@FN1@@", f1).replace("@@FN2@@", f2))
        table = dict(l.split("=", 1) for l in (out or "").splitlines() if "=" in l)
        exp = {
            "029E/029E/1": "67.0 25k|8", "029E/0375/1": "R67.0 T88.5 25k|15", "029E/FFFF/1": "R67.0 25k|9", "FFFF/0375/0": "T88.5 12.5k|11", "FFFF/FFFF/1": "25k|3", "0000/0000/0": "12.5k|5",
            "8023/8023/1": "D023N 25k|9", "8023/C754/0": "RD023N TD754I 12.5k|19", "8023/029E/1": "RD023N T67.0 25k|16", "09ED/09ED/0": "254.1 12.5k|11",
            "09ED/09C4/0": "R254.1 T250.0 12.5k|19", "C754/09ED/0": "RD754I T254.1 12.5k|19",
        }
        check(all(table.get(k) == v for k, v in exp.items()), "К2: таблиця прикладів тонів (RX/TX/смуга): %s" % {k: table.get(k) for k in exp if table.get(k) != exp[k]})
        check(all(int(v.rsplit("|", 1)[1]) <= 19 for v in table.values()), "К2: жоден рядок 3 не довший за 19 символів (DW_LINE3_MAX)")
        base = out
        muts = (("тони не розрізняє R/T", f2.replace('(same ? "" : "R")', '""')), ("не скорочує однакові", re.sub(r"same = \(rxTone == txTone\)", "same = 0", f2)),
                ("смуга не додається", f2.replace('(bw25 ? "25k" : "12.5k")', '""')))
        for what, m in muts:
            mo = run_in(TONE_HARNESS.replace("@@FN1@@", f1).replace("@@FN2@@", m)) if m != f2 else None
            check(m != f2 and mo is not None and mo != base, "К2 (мутант): %s -- ловиться" % what)
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    check("dualFmToneLine(l3, sizeof(l3), rec->rxTone, rec->txTone," in uc, "К2: рядок 3 FM будується з rxTone/txTone запису (канал і VFO -- один шлях rec)")
    check("CTCSS %d.%d" not in uc[uc.find("static void dualRenderRow("):uc.find("static void dualRenderRow(") + 6000], "К2: старий показ лише RX-тону прибрано")
    # --- К1 відстань
    if "static void dualAppendDistance(" not in uc:
        print("ПРОПУСК: К1 -- відстань перенесено з рядка 3 у рядок 4 картки (R98-FIX5 Б2, dualRow4Text, зі стрілкою); умови й мутанти перевіряє tools/test_r98fix5.py")
        return
    f3 = T.carve_fn(tc or "", "void dualAppendDistance(char *l3)")
    check(f3 is not None, "К1: dualAppendDistance знайдено (під LC_DISTANCE)")
    if f3:
        out = run_in(DIST_HARNESS.replace("@@FN@@", f3))
        o = kv(out)
        exp = {"ok": "TS1 CC1 TG91 123m", "km": "TS1 CC1 TG91 532km", "noown": "TS1 CC1 TG91", "nocoord": "TS1 CC1 TG91", "bad": "TS1 CC1 TG91", "full": "TS1 CC1 TG 1234567", "exact": "TS1 CC1 TG 123 123m"}
        check(all(o.get(k) == v for k, v in exp.items()), "К1: відстань додається лише за умов шапки виклику і лише якщо влазить у 19 символів: %s" % o)
        for what, m in (("без перевірки своєї позиції", f3.replace("settingsLocationIsValid() &&", "1 &&")), ("без перевірки координат цього виклику", f3.replace("(LinkHead->locationLat <= 90) &&", "")),
                        ("без перевірки «влазить»", re.sub(r"&&\s*\(\(n \+ 1U \+ strlen\(label\)\) <= \d+\)", "", f3))):
            mo = run_in(DIST_HARNESS.replace("@@FN@@", m)) if m != f3 else None
            check(m != f3 and mo is not None and mo != out, "К1 (мутант): %s -- ловиться" % what)
    uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    qi = uu.find("static bool qsoShowNameWithDistance(")
    qb = uu[qi:qi + 1200]
    for pred in ("LinkHead->locationLat <= 90", "settingsLocationIsValid()", "lcDistLabel("):
        check(pred in qb and pred in uc[uc.find("static void dualAppendDistance("):uc.find("static void dualAppendDistance(") + 900], "К1: та сама умова, що й підпис «[відстань]» шапки: %s" % pred)
    check(re.search(r"#if defined\(LC_DISTANCE\)\n\t\t\tif \(callerHere\)\n\t\t\t\{\n\t\t\t\tdualAppendDistance\(l3\);", uc) is not None, "К1: відстань лише на картці активного виклику (callerHere), під LC_DISTANCE")
    check("lcDistArrowGeom" not in uc[uc.find("static void dualRenderRow("):uc.find("static void dualRenderRow(") + 9000], "К1: стрілка не малюється (немає вільної комірки 10x10 -- таблиця координат у результаті)")


# ------------------------------------------------------------------------------------------------ Е
def test_part_e():
    d = tempfile.mkdtemp(prefix="r98f2e_")
    try:
        # справжній тест (tests/run_tests.sh aes_retune) + мутанти функції в копії dmr_aes_hook.c
        hook = T.rd(os.path.join(APP, "source", "crypto", "dmr_aes_hook.c"))
        tsrc = T.rd(os.path.join(FW, "tests", "test_aes_retune.c"))
        flags = FW_INCS + ["-DUSE_HAL_DRIVER", "-DSTM32F405xx", "-DPLATFORM_MDUV380", "-DPLATFORM_VARIANT_UV380_PLUS_10W", "-DNDEBUG", "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_AES", "-DENABLE_DMR_DATA", "-DENABLE_DUAL_CHANNEL",
                                "-I" + os.path.join(INC, "crypto"), "-std=gnu11", "-w", "-Wno-int-to-pointer-cast"]

        def run(hooktext):
            os.makedirs(os.path.join(d, "t"), exist_ok=True)
            hp = os.path.join(d, "dmr_aes_hook.c"); open(hp, "w", encoding="utf-8").write(hooktext)
            tp = os.path.join(d, "t", "test_aes_retune.c")
            open(tp, "w", encoding="utf-8").write(tsrc.replace('#include "../application/source/crypto/dmr_aes_hook.c"', '#include "%s"' % hp))
            exe = os.path.join(d, "t", "x")
            r = subprocess.run(["gcc"] + flags + [tp, os.path.join(APP, "source", "crypto", "dmr_aes.c"), os.path.join(FN, "dmr_sms_text.c"), "-o", exe], capture_output=True)
            if r.returncode != 0:
                return (-1, r.stderr.decode()[:800])
            p = subprocess.run([exe], capture_output=True)
            return (p.returncode, p.stdout.decode())
        rc, out = run(hook)
        check(rc == 0 and "ПРОЙДЕНО" in out, "Е: dmrAesRxRetune скидає стан RX AES попереднього каналу (справжній dmr_aes_hook.c): %s" % out[-200:])
        fi = hook.find("void dmrAesRxRetune(void)"); fe = hook.find("\n}\n", fi)
        body = hook[fi:fe]
        for what, old in (("ключ останнього виклику", "    s_rxKeyId = 0;\n"), ("активність розшифровки", "    s_rxActive = 0;\n"), ("кандидат PI", "    s_rxPendMi = 0;\n    s_rxPendKeyId = 0;\n")):
            m = hook[:fi] + body.replace(old, "", 1) + hook[fe:]
            rc2, out2 = run(m) if m != hook else (0, "ПРОЙДЕНО")
            check(m != hook and (rc2 != 0), "Е (мутант): не скидається %s -- ловиться" % what)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    ti = uc.find("static void dualTune(bool toB)\n{")
    te = uc.find("\n}\n", ti)
    check("dmrAesRxRetune();" in uc[ti:ti + 400], "Е: dualTune скидає RX AES першим кроком (до зміни каналу)")
    sites = [m.start() for m in re.finditer(r"dcSetOnB\(", uc)]
    inside = [p for p in sites if ti < p < te]
    other = [uc.count("\n", 0, p) + 1 for p in sites if not (ti < p < te)]
    # інші місця, де рація перестає стояти на B/A без dualTune: лише службові (видалення B, вихід) -- перелічуємо
    check(len(inside) == 2, "Е: A<->B перемикає лише dualTune (два dcSetOnB усередині); інші виклики dcSetOnB: рядки %s" % other)
    hk = T.rd(os.path.join(APP, "source", "crypto", "dmr_aes_hook.c"))
    check(hk.count("static uint8_t       s_rxKeyId DMR_AES_CCM;") == 1 and "dmrAesRxRetune" in T.rd(os.path.join(INC, "crypto", "dmr_aes_hook.h")), "Е: нових змінних нема (CCM-стан той самий), функція оголошена")


# ------------------------------------------------------------------------------------------------ Є
TUNE_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
typedef struct { uint32_t rxFreq; uint8_t power; uint8_t sql; char tag; } CodeplugChannel_t;
static CodeplugChannel_t channelScreenChannelData, scanNextChannelData, settingsVFOChannel[2];
static CodeplugChannel_t *currentChannelData;
static struct { int currentSelectedChannelNumber; } uiDataGlobal;
static struct { int16_t currentIndexInTRxGroupList[4]; } nonVolatileSettings;
#define SETTINGS_CHANNEL_MODE 0
static int16_t s_dualTgIdxA;
static int onB, bIsVfo, chB = 7, vfoIdx, retunes, vfoLoads, loadMem = -1, loads;
static bool dcIsOnB(void) { return onB; }
static void dcSetOnB(bool b) { onB = b; }
static bool dcBIsVfo(void) { return bIsVfo; }
static uint16_t dcChannelB(void) { return (uint16_t)chB; }
static uint8_t dualVfoIdx(void) { return (uint8_t)vfoIdx; }
static void lastHeardClearLastID(void) { }
static void dmrAesRxRetune(void) { retunes++; }
static void uiVFOModeDualLoad(uint8_t i, bool b) { (void)i; (void)b; vfoLoads++; }
static void codeplugChannelGetDataForIndex(uint16_t ch, CodeplugChannel_t *c) { memset(c, 0, sizeof *c); c->rxFreq = 1000u + ch; c->power = 1; c->tag = 'B'; }
static void uiChannelModeLoadChannelData(bool m, bool v) { (void)v; loadMem = m; loads++; }
static void settingsSetBOOL(bool *p, bool v) { *p = v; }
static void settingsSetINT8(int8_t *p, int8_t v) { *p = v; }
static void settingsSetUINT8(uint8_t *p, uint8_t v) { *p = v; }
static void settingsSetINT16(int16_t *p, int16_t v) { *p = v; }
static void settingsSetUINT16(uint16_t *p, uint16_t v) { *p = v; }
static void settingsSetINT32(int32_t *p, int32_t v) { *p = v; }
static void settingsSetUINT32(uint32_t *p, uint32_t v) { *p = v; }
@@FN@@
static void startA(void) { onB = 0; currentChannelData = &channelScreenChannelData; channelScreenChannelData.rxFreq = 438500; channelScreenChannelData.power = 9; channelScreenChannelData.tag = 'A'; scanNextChannelData.tag = 'x'; scanNextChannelData.power = 0; }
static void st(const char *n) { printf("%s=%c%u|%c%u|ptr%d\n", n, channelScreenChannelData.tag, channelScreenChannelData.power, scanNextChannelData.tag, scanNextChannelData.power, currentChannelData == &channelScreenChannelData ? 0 : (currentChannelData == &settingsVFOChannel[0] ? 1 : 2)); }
int main(void)
{
	/* s1: B = канал: A -> B -> A */
	bIsVfo = 0; startA(); dualTune(1); st("s1b"); dualTune(0); st("s1a"); printf("s1m=%d,%d\n", loadMem, onB);
	/* s2: три заходи */
	startA(); dualTune(1); dualTune(0); dualTune(1); dualTune(0); dualTune(1); dualTune(0); st("s2");
	/* s3: B = VFO */
	bIsVfo = 1; startA(); dualTune(1); st("s3b"); dualTune(0); st("s3a");
	/* s4: канал -> VFO -> канал -> A */
	bIsVfo = 0; startA(); dualTune(1); bIsVfo = 1; dualTune(1); st("s4v"); bIsVfo = 0; dualTune(1); st("s4c"); dualTune(0); st("s4a");
	/* s5: крок B між каналами (B1 -> B2): копія A не перезаписується даними B1 */
	bIsVfo = 0; startA(); dualTune(1); chB = 9; dualTune(1); st("s5b"); dualTune(0); st("s5a"); chB = 7;
	/* s6: буфер скинуто меню зон/кодплага (rxFreq = 0) -> стокове перечитування зони */
	bIsVfo = 1; startA(); dualTune(1); channelScreenChannelData.rxFreq = 0; dualTune(0); printf("s6m=%d\n", loadMem);
	printf("rt=%d\n", retunes > 0);
	return 0;
}
'''


def test_part_ye(incs, cf):
    tc = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = T.carve_fn(tc or "", "void dualTune(_Bool toB)")
    bh = T.carve_fn(tc or "", "_Bool dualBufHoldsB(void)")
    check(fn is not None and bh is not None, "Є: dualTune/dualBufHoldsB знайдено")
    if not (fn and bh):
        return
    code = TUNE_HARNESS.replace("@@FN@@", bh + "\n" + fn)
    out = run_in(code); o = kv(out)
    exp = {"s1b": "B1|A9|ptr0", "s1a": "A9|A9|ptr0", "s1m": "1,0", "s2": "A9|A9|ptr0", "s3b": "A9|x0|ptr1", "s3a": "A9|x0|ptr0", "s4v": "A9|A9|ptr1", "s4c": "B1|A9|ptr0", "s4a": "A9|A9|ptr0",
           "s5b": "B1|A9|ptr0", "s5a": "A9|A9|ptr0", "s6m": "0", "rt": "1"}
    check(all(o.get(k) == v for k, v in exp.items()), "Є: правки A (потужність=9) живуть через заходи на B (канал/VFO/зміна B/кілька заходів): %s" % {k: (o.get(k), exp[k]) for k in exp if o.get(k) != exp[k]})
    muts = (("A не зберігається перед B", fn.replace("memcpy(&scanNextChannelData, &channelScreenChannelData, sizeof(CodeplugChannel_t));", "")),
            ("A не відновлюється при поверненні", fn.replace("memcpy(&channelScreenChannelData, &scanNextChannelData, sizeof(CodeplugChannel_t));", "")),
            ("A перечитується з кодплага (стара поведінка)", fn.replace("uiChannelModeLoadChannelData((channelScreenChannelData.rxFreq != 0U), 0);", "uiChannelModeLoadChannelData(0, 0);")),
            ("копія A перезаписується при кроці B", fn.replace("if ((bufHoldsB == 0) && (0 == 0))", "if (1)").replace("if (bufHoldsB == 0)", "if (1)")))
    for what, m in muts:
        mo = run_in(TUNE_HARNESS.replace("@@FN@@", bh + "\n" + m)) if m != fn else None
        mk = kv(mo) if mo else {}
        check(m != fn and mo is not None and any(mk.get(k) != v for k, v in exp.items()), "Є (мутант): %s -- ловиться" % what)
    # зберігання: нічого не пишемо в кодплаг; нових буферів нема
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    ti = uc.find("static void dualTune(bool toB)\n{"); te = uc.find("\n}\n", ti)
    check("codeplugChannelSave" not in uc[ti:te] and "Save(" not in uc[ti:te], "Є: dualTune нічого не пише в кодплаг (жодного автозбереження)")
    check(len(re.findall(r"static CodeplugChannel_t \w+", uc)) == 1, "Є: нового буфера CodeplugChannel_t нема (використано наявний scanNextChannelData)")


# ------------------------------------------------------------------------------------------------ Ж
def load_font(name, enc="latin-1"):
    t = T.rd(os.path.join(INC, "hardware", "HX8353E_charset_UA.h"), enc)
    i = t.index("const uint8_t " + name + "[]"); j = t.index("};", i)
    body = re.sub(r"//[^\n]*", "", t[t.index("{", i) + 1:j])
    return bytes(int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", body))


def missing_cyr(font, compressed):
    out = []
    p = 8
    for c in range(font[2], font[3] + 1):
        if compressed:
            n = font[p]; empty = (n == 0 or all(font[p + 1 + 2 * k] == 0 for k in range(n))); p += n * 2 + 1
        else:
            bpc = font[7]; chunk = font[8 + (c - font[2]) * bpc:8 + (c - font[2]) * bpc + bpc]; empty = not any(chunk)
        if c >= 192 and empty:
            out.append(c)
    return out


def test_part_zh():
    f16 = load_font("font_16x32_compressed"); bold = load_font("font_6x8_bold")
    m16 = missing_cyr(f16, True); mb = missing_cyr(bold, False)
    check(m16 == [198, 215, 222, 230, 247, 254] and mb == [198, 215, 222, 230, 247, 254], "Ж: літери без гліфів у 16x32 і 6x8 bold (cp1251): Ж Ч Ю ж ч ю = %s / %s" % (m16, mb))
    miss = set(m16) | set(mb)
    ua = T.rd(os.path.join(APP, "include", "user_interface", "languages", "ukrainian.h"), "cp1251")
    fields = dict(re.findall(r"\.(\w+)\s*=\s*\"([^\"]*)\"", ua))
    rows = []
    for root, _, files in os.walk(os.path.join(APP, "source")):
        for f in files:
            if not f.endswith(".c"): continue
            t = T.rd(os.path.join(root, f))
            for m in re.finditer(r"[^\n;]*FONT_SIZE_(?:4\b|1_BOLD)[^\n;]*", t):
                line = m.group(0)
                for fld in re.findall(r"currentLanguage->(\w+)", line):
                    s = fields.get(fld)
                    rows.append((os.path.relpath(os.path.join(root, f), APP), fld, "FONT_SIZE_4" if "FONT_SIZE_4" in line else "FONT_SIZE_1_BOLD", s))
    bad = [(a, b, c, s) for a, b, c, s in rows if s is not None and any(ord(ch.encode("cp1251")[0:1]) in miss for ch in s if ord(ch) > 127)]
    check(len(rows) >= 4, "Ж: знайдено місця, де мовні рядки виводяться 16x32/bold: %s" % [(a, b, c) for a, b, c, _ in rows])
    check(not bad, "Ж: жоден український мовний рядок із літерами Ж/Ч/Ю не виводиться шрифтом без гліфів: %s" % bad)
    # повноекранні повідомлення режиму (uiNotificationShowShort) -- FONT_SIZE_3 (повна кирилиця)
    un = T.rd(os.path.join(UI, "uiNotification.c"))
    ci = un.find("static void displayMessageCard(void)\n{"); ce = un.find("displayPrintCentered(y, line[i], FONT_SIZE_3);", ci) + 60; check(ce > ci + 60, "Ж: вивід рядків картки (FONT_SIZE_3) знайдено")
    check("FONT_SIZE_4" not in un[ci:ce] and "FONT_SIZE_3" in un[ci:ce], "Ж: повноекранна картка повідомлень («B видалено», «Зона: Всі канали» тощо) малює FONT_SIZE_3, не 16x32")
    f8 = load_font("font_8x16")
    check(missing_cyr(f8, False) == [], "Ж: FONT_SIZE_3 (8x16) має всі літери cp1251 192..255")
    # мутант: поле з «Ж» у FONT_SIZE_4 -- перевірка дійсно ловить
    check(any(ord(c.encode("cp1251")[0:1]) in miss for c in "ЖЧЮжчю"), "Ж (мутант): критерій ловить рядок з Ж/Ч/Ю")


# ------------------------------------------------------------------------------------------------ Л
HINT_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#define DISPLAY_SIZE_X 160
typedef enum { FONT_SIZE_2 = 2 } ucFont_t;
typedef enum { TEXT_ALIGN_LEFT = 0 } ucTextAlign_t;
static int draws, fills, minx = 999, maxx = -1, miny = 999, maxy = -1, hl = -2, hlcount;
static char shown[64];
static void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { (void)inv; fills++; hl = x; hlcount++; if (x < minx) minx = x; if (x + w > maxx) maxx = x + w; (void)y; (void)h; }
static void displayPrintCore(int16_t x, int16_t y, const char *s, int f, int a, bool inv) { (void)f; (void)a; (void)inv; draws++; if (x < minx) minx = x; if (x + 8 > maxx) maxx = x + 8; if (y < miny) miny = y; if (y + 8 > maxy) maxy = y + 8; strcat(shown, s); }
@@FN@@
int main(int argc, char **argv)
{
	const char *map = argv[1]; int idx = atoi(argv[2]);
	uiSmsKeyHintMap(map, idx, 2, 116);
	printf("minx=%d\nmaxx=%d\nminy=%d\nmaxy=%d\nhlcount=%d\nhl=%d\ndraws=%d\nshown=%s\n", minx, maxx, miny, maxy, hlcount, hl, draws, shown);
	return 0;
}
'''


def run_hint(fnsrc, map_, idx):
    d = tempfile.mkdtemp(prefix="r98f2l_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(HINT_HARNESS.replace("@@FN@@", fnsrc).replace("#include <stdbool.h>", "#include <stdbool.h>\n#include <stdlib.h>"))
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:800]); return None
        p = subprocess.run([os.path.join(d, "h"), map_, str(idx)], capture_output=True)
        return kv(p.stdout.decode())
    finally:
        shutil.rmtree(d, ignore_errors=True)


TRACE_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#define DISPLAY_SIZE_X 160
typedef enum { FONT_SIZE_2 = 2 } ucFont_t;
typedef enum { TEXT_ALIGN_LEFT = 0 } ucTextAlign_t;
static void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { printf("F%d,%d,%d,%d,%d;", x, y, w, h, inv); }
static void displayPrintCore(int16_t x, int16_t y, const char *s, int f, int a, bool inv) { printf("P%d,%d,%s,%d,%d,%d;", x, y, s, f, a, inv); }
@@FN@@
int main(int argc, char **argv) { uiSmsKeyHintMap(argv[1], atoi(argv[2]), 2, 116); printf("\\n"); return 0; }
'''


def run_trace(fnsrc, map_, idx):
    d = tempfile.mkdtemp(prefix="r98f2t_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(TRACE_HARNESS.replace("@@FN@@", fnsrc))
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:800]); return None
        return subprocess.run([os.path.join(d, "h"), map_, str(idx)], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_part_l():
    ks = T.rd(os.path.join(UI, "uiSmsKeys.c"))
    fn = T.carve_fn(ks, "void uiSmsKeyHintMap(const char *map, int idx, int16_t x, int16_t y)")
    check(fn is not None, "Л: uiSmsKeyHintMap знайдено")
    kb = T.rd(os.path.join(APP, "source", "io", "keyboard.c"))
    maps = re.findall(r'^\t\t"([^"\n]+)"[,]?\s*$', kb[kb.find("keypadAlphaMap[11][31]"):kb.find("#define KEYBOARD_KEYS_PER_ROW")], re.M)
    check(len(maps) == 11, "Л: таблиця стокової клавіатури (11 клавіш) прочитана з keyboard.c, не продубльована: %d" % len(maps))
    if fn and len(maps) == 11:
        okall = True; bad = []
        for mp in maps:
            n = len(mp)
            for idx in range(-1, n):
                o = run_hint(fn, mp, idx)
                if o is None or int(o["minx"]) < 2 or int(o["maxx"]) > 160 or int(o["miny"]) < 116 or int(o["maxy"]) > 124:
                    okall = False; bad.append((mp, idx, o and (o["minx"], o["maxx"], o["miny"], o["maxy"])))
                elif idx >= 0 and int(o["hlcount"]) != 1:
                    okall = False; bad.append((mp, idx, "hl%s" % o["hlcount"]))
                elif idx < 0 and int(o["hlcount"]) != 0:
                    okall = False; bad.append((mp, idx, "hl%s" % o["hlcount"]))
        check(okall, "Л: підказка (11 клавіш x усі позиції): x у 2..160, y у 116..124, рівно одне виділення (або жодного при idx=-1): %s" % bad[:3])
        # регресія: стара функція (база) і нова віддають те саме для SMS-розкладок
        if base_available():
            old = base_file("application/source/user_interface/uiSmsKeys.c")
            ofn = T.carve_fn(old or "", "void uiSmsKeyHint(uint8_t mode, char key, uint8_t idx, int16_t x, int16_t y)")
            check(ofn is not None, "Л: стара uiSmsKeyHint знайдено в базі для порівняння")
            if ofn:
                oldw = ("static const char *g_map;\nstatic const char *smsMtKeyMap(uint8_t m, char k) { (void)m; (void)k; return g_map; }\n" + ofn +
                        "\nvoid uiSmsKeyHintMap(const char *map, int idx, int16_t x, int16_t y) { g_map = map; uiSmsKeyHint(0, '1', (uint8_t)idx, x, y); }\n")
                diff = []
                for mp in maps + ["1.,?!'-@:;/()&#+=_<>2", "abc", " 0"]:
                    for idx in range(0, len(mp)):
                        a1 = run_trace(fn, mp, idx); a2 = run_trace(oldw, mp, idx)
                        if a1 is None or a1 != a2:
                            diff.append((mp, idx))
                check(not diff, "Л: нова спільна uiSmsKeyHintMap малює ТЕ САМЕ, що стара uiSmsKeyHint (бази %s), для всіх клавіш і позицій: %s" % (BASE, diff[:3]))
        else:
            print("ПРОПУСК: база недоступна (CI/клон без історії)")
    check(ks.count("uiSmsKeyHintMap(smsMtKeyMap(mode, key), (int)idx, x, y);") == 1, "Л: uiSmsKeyHint (повідомлення/APRS) тепер лише викликає спільну uiSmsKeyHintMap")
    mc = T.rd(os.path.join(UI, "menuChannelDetails.c"))
    check("abc2" not in mc and "abc2" not in ks and "ABC2" not in mc, "Л: таблиць літер у menuChannelDetails.c/uiSmsKeys.c не продубльовано")
    check("#define CH_NAME_KEY_HINT 1" in mc and "#if defined(LANGUAGE_BUILD_UKRAINIAN) && ((defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX))\n#define CH_NAME_KEY_HINT 1" in mc,
          "Л: підказка лише в українській збірці (та сама умова, що й uiSmsKeys.c)")
    blocks = [m.start() for m in re.finditer(r"keypadAlphaPreviewMap\(&alphaIdx\)", mc)]
    check(len(blocks) == 1, "Л: підказку малює один блок")
    bi = mc.rfind("#if defined(CH_NAME_KEY_HINT)", 0, blocks[0])
    check("menuDataGlobal.currentItemIndex == CH_DETAILS_NAME" in mc[bi:blocks[0]] and "settingOption == false" in mc[bi:blocks[0]], "Л: лише на пункті «Назва» (і не під час вибору опції)")
    check("CH_DETAILS_VFO_CHANNEL" in mc[bi:blocks[0]], "Л: не на VFO (де «Назви» нема)")
    ki = kb.find("const char *keypadAlphaPreviewMap(int *idx)")
    check(ki > 0 and kb.rfind("#if defined(LANGUAGE_BUILD_UKRAINIAN)", 0, ki) > kb.rfind("#endif", 0, ki - 1) - 0, "Л: акцесор клавіатури під LANGUAGE_BUILD_UKRAINIAN")
    # геометрія: рядки меню MDUV380 (7 пунктів по 16 px від y=16); підказка замінює останній
    ug = T.rd(os.path.join(INC, "user_interface", "uiGlobals.h"))
    rows = [(16 + 16 * k, 16) for k in range(7)]
    hint = (2, 116, 158, 8)
    over = [i for i, rr in enumerate(rows) if rects_overlap((0, rr[0], 160, rr[1]), hint)]
    check(over == [6], "Л: підказка (y=116..123) перетинає лише останній (7-й) пункт списку, який на цей час не малюється: %s" % over)
    check("if (nameHint && (i == MENU_END_ITERATION_VALUE))" in mc, "Л: пропускається саме останній пункт (MENU_END_ITERATION_VALUE)")
    check("#define CH_NAME_HINT_Y   (DISPLAY_SIZE_Y - 12)" in mc, "Л: y підказки = DISPLAY_SIZE_Y - 12 (116)")
    check("#define DISPLAY_Y_POS_MENU_START             (16 + MENU_ENTRY_HEIGHT)" in ug, "Л: геометрія меню: перший пункт y=32 для DM1701/UV380 (список)")


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    test_part_d(incs, cf)
    test_part_k(incs, cf)
    test_part_e()
    test_part_ye(incs, cf)
    test_part_zh()
    test_part_l()
    print("test_r98fix2: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
