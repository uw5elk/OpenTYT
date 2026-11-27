#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R107-CPSUSB, частина Б (В4): діагностичні USB-команди лише в збірках з ENABLE_USB_DIAG (типово 1; build-ukrainian -- 0).

Препроцесор хостового gcc (ті самі -I і -D, що в tools/syntax_check.sh) проганяє usb_com.c і dmr_rctl_cap.c у двох
конфігураціях: SMSF (як CI build-ukrainian до R107) і USBOFF (SMSF + -DUSB_DIAG_OFF, як build-ukrainian після R107).
  Б1  USBOFF: case 0x86/0x8A/0x8B/0x91/0x92/0x98/0x99/0x9A зникли; 0x9B -- лише кабельне розблокування (без лічильників).
  Б2  SMSF (з командами): усі ці case на місці, 0x9B -- з лічильниками (dmrRctlStockRxDiag).
  Б3  Не зачеплено в обох: 0x80, 0x81, 0x82, 0x83, 0x90, 0x9C.
  Б4  Невідомий код (зокрема прибраний): обробник закінчується default -> загальна відповідь '-' (1 байт), як для будь-якої
      невідомої команди сьогодні; нової гілки для прибраних кодів нема.
  Б5  dmr_rctl_cap.c у USBOFF: кільця s_ring нема, заглушки (dmrRctlCapArmed -> 0).
  Б6  Makefile: ENABLE_USB_DIAG=0 -> -DUSB_DIAG_OFF; типово (і =1) -- нема. build.yml: ENABLE_USB_DIAG=0 лише в build-ukrainian.
  Б7  CPS/прошивальник/відновлення (cps_ui, cps_restore, custom_region, gui_flasher, cps_link ...) прибраних кодів не шлють.
  Б8  tools/rctl_capture.py розуміє коротку відповідь 0x9B (4 байти) робочої збірки.
  Б9  Мутант: «без -DUSB_DIAG_OFF» Б1 ловить.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(FW, ".."))
FAILS = []
GATED = ["0x86", "0x8A", "0x8B", "0x91", "0x92", "0x98", "0x99", "0x9A"]
KEPT = ["0x80", "0x81", "0x82", "0x83", "0x90", "0x9C"]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def preprocess(src, cfg, extra=()):
    """gcc -E з масивами INCS і DEFS_<cfg> з syntax_check.sh. None, якщо gcc нема."""
    if shutil.which("gcc") is None:
        return None
    sh = open(os.path.join(HERE, "syntax_check.sh"), encoding="utf-8").read()
    a = sh.index("\nINCS=(")
    b = sh.index("\nCONFIGS=(")
    script = sh[a:b] + '\nexec gcc -E -P -std=gnu11 "${INCS[@]}" "${DEFS_%s[@]}" %s "$1"\n' % (cfg, " ".join(extra))
    r = subprocess.run(["bash", "-c", script, "pp", src], cwd=FW, capture_output=True, text=True)
    if r.returncode != 0:
        check(False, "gcc -E %s (%s): %s" % (src, cfg, r.stderr[-400:]))
        return ""
    return r.stdout


def case_body(pp, code):
    """Текст від `case CODE:` до наступного case/default (на рівні тексту -- для перевірок наявності викликів)."""
    m = re.search(r"case\s+%s\s*:" % code, pp, re.I)
    if not m:
        return None
    n = re.search(r"\bcase\s+0x[0-9A-Fa-f]+\s*:|\bdefault\s*:", pp[m.end():])
    return pp[m.end():m.end() + (n.start() if n else 2000)]


def has_case(pp, code):
    return re.search(r"case\s+%s\s*:" % code, pp, re.I) is not None


def check_off(pp, tag="Б1"):
    for c in GATED:
        check(not has_case(pp, c), "%s: у USBOFF нема case %s" % (tag, c))
    body = case_body(pp, "0x9B")
    check(body is not None and "dmrRctlSetInhibited" in body and "dmrRctlIsInhibited" in body and "dmrRctlStockRxDiag" not in body,
          "%s: 0x9B у USBOFF -- лише розблокування й стан, без лічильників" % tag)


def main():
    usb = "application/source/usb/usb_com.c"
    cap = "application/source/functions/dmr_rctl_cap.c"
    on = preprocess(usb, "SMSF")
    if on is None:
        print("ПРОПУСК: gcc нема -- перевірки препроцесора (Б1-Б5, Б9) не виконано")
    else:
        off = preprocess(usb, "USBOFF")
        check_off(off)
        for c in GATED:
            check(has_case(on, c), "Б2: у SMSF є case %s" % c)
        b9 = case_body(on, "0x9B")
        check(b9 is not None and "dmrRctlStockRxDiag" in b9, "Б2: 0x9B у SMSF -- з лічильниками")
        for c in KEPT:
            check(has_case(on, c) and has_case(off, c), "Б3: case %s є в обох" % c)
        for name, pp in (("SMSF", on), ("USBOFF", off)):
            m = re.search(r"default\s*:\s*break\s*;\s*\}\s*usbComSendBuf\[0\]\s*=\s*'-'\s*;\s*hasToReply\s*=\s*(?:true|1)\s*;\s*replyLength\s*=\s*1\s*;", pp)
            check(m is not None, "Б4: %s -- невідомий код: default -> '-' (1 байт)" % name)
        check(off.count("usbComSendBuf[0] = '-'") == on.count("usbComSendBuf[0] = '-'"),
              "Б4: нових відповідей '-' не додано (та сама загальна гілка)")
        capoff = preprocess(cap, "USBOFF")
        capon = preprocess(cap, "SMSF")
        check("s_ring" not in capoff and re.search(r"int\s+dmrRctlCapArmed\s*\(\s*void\s*\)\s*\{\s*return\s+0\s*;", capoff) is not None,
              "Б5: dmr_rctl_cap.c у USBOFF -- без кільця, dmrRctlCapArmed() == 0")
        check("s_ring" in capon, "Б5: dmr_rctl_cap.c у SMSF -- кільце є")
        # Б9: мутант -- без -DUSB_DIAG_OFF перевірка Б1 мусить впасти
        global FAILS
        saved, FAILS = FAILS, []
        import builtins
        p = builtins.print
        builtins.print = lambda *a, **k: None
        try:
            check_off(on, "мутант")
        finally:
            builtins.print = p
        caught = bool(FAILS)
        FAILS = saved
        check(caught, "Б9: мутант «без -DUSB_DIAG_OFF» не спіймано")

    mk = open(os.path.join(FW, "Makefile"), encoding="utf-8").read()
    check(re.search(r"^ENABLE_USB_DIAG \?= 1$", mk, re.M) is not None, "Б6: Makefile -- ENABLE_USB_DIAG ?= 1")
    check(re.search(r"ifeq \(\$\(ENABLE_USB_DIAG\),0\)\s*\nDEFS \+= -DUSB_DIAG_OFF\s*\nendif", mk) is not None,
          "Б6: Makefile -- ENABLE_USB_DIAG=0 -> -DUSB_DIAG_OFF")
    yml = open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8").read()
    jobs = re.split(r"\n  (?=[a-z][a-z0-9-]*:\n)", yml)
    users = [j.split(":", 1)[0] for j in jobs if re.search(r"^\s*run: make .*ENABLE_USB_DIAG=0", j, re.M)]
    check(users == ["build-ukrainian"], "Б6: ENABLE_USB_DIAG=0 лише в build-ukrainian: %r" % users)
    check(not re.search(r"ENABLE_USB_DIAG=1", yml), "Б6: build.yml ніде не вмикає явно (типово 1)")

    # Б7: інструменти CPS не шлють прибраних кодів
    pat = re.compile(r'ord\(["\']C["\']\)\s*,\s*(0x(?:86|8[aAbB]|9[12]|9[89aA]))\b|SUB_[A-Z_]+\s*=\s*(0x(?:86|8[aAbB]|9[12]|9[89aA]))\b')
    cps_files = [os.path.join(HERE, f) for f in ("cps_restore.py", "custom_region.py", "cps_link.py", "doc_region.py", "custom_data.py",
                                                  "flash_guard.py", "gui_flasher.py", "aes_key_store.py", "aes_keys_backup.py")]
    cps_files += [os.path.join(HERE, "cps_ui", f) for f in os.listdir(os.path.join(HERE, "cps_ui")) if f.endswith(".py")]
    for f in cps_files:
        if not os.path.exists(f):
            continue
        t = open(f, encoding="utf-8").read()
        m = pat.search(t)
        check(m is None, "Б7: %s шле прибраний код %s" % (os.path.relpath(f, FW), m and (m.group(1) or m.group(2))))

    # Б8: rctl_capture.py -- коротка відповідь 0x9B
    rc = open(os.path.join(HERE, "rctl_capture.py"), encoding="utf-8").read()
    check("len(body) == 4" in rc and "ENABLE_USB_DIAG" in rc, "Б8: rctl_capture.py розпізнає коротку відповідь 0x9B робочої збірки")
    for f in ("dmr_data_tx.py", "rctl_capture.py", os.path.join("lab", "menu_sms_test.py")):
        t = open(os.path.join(HERE, f), encoding="utf-8").read()
        check("ENABLE_USB_DIAG" in t[:3000], "Б8: %s -- примітка «потрібна діагностична збірка (ENABLE_USB_DIAG)» у шапці" % f)

    if FAILS:
        print("test_r107usb: ПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r107usb: усе гаразд (діагностичні USB-команди лише з ENABLE_USB_DIAG; 0x9B -- розблокування; невідомий код -> '-'; мутант)")


if __name__ == "__main__":
    main()
