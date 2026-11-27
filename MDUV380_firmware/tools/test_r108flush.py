#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R108-FLUSHFIX (правка 1): дозапис відкладених SMS DMR / APRS перед перезавантаженням з CPS ('C' 6 0 / 'C' 6 1).

Що перевіряємо (потрібен gcc; без нього -- ПРОПУСК із поясненням, не «пройдено»):
  Ф1  препроцесор (ті ж -I/-D, що в syntax_check.sh): у конфігураціях SMSF (build-ukrainian) обидва шляхи перезавантаження ('C' 6 0 і 'C' 6 1) викликають
      cpsFlushDeferredStores() ПЕРЕД addTimerCallback(NVIC_SystemReset); у DEF/AES1 (без прапорців) -- жодного сліду (збірки без прапорців не змінено).
  Ф2  допоміжна функція (справжній текст із usb_com.c) зібрана з заглушками: порядок -- спершу APRS, потім SMS (як у batteryAndPowerManagement.c);
      обидва Flush викликаються при ЗНЯТІЙ критичній секції (TASK_UNLOCK_WRITE до, TASK_LOCK_WRITE після) -- запис у флеш чекає (osDelay).
  Ф3  порядок і #if збігаються з powerDown/powerOffFinalStage (battery...c): ті самі два виклики в тому самому порядку.
  Ф4  мутанти: без виклику в 'C' 6 1; без виклику в 'C' 6 0; порядок SMS->APRS; Flush усередині критичної секції -- ловляться.
Функціональну частину (відкладене вхідне SMS після Flush у режимі UI_CPS потрапляє в кільце) дає tests/test_dmr_sms_flash.c, крок 7b
(через test_r106smsstore.py); APRS -- aprsMsgStoreFlushCore не має гейтів (test_r101aprsmsg.py).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
USB = os.path.join(FW, "application", "source", "usb", "usb_com.c")
BP = os.path.join(FW, "application", "source", "interfaces", "batteryAndPowerManagement.c")
FAILS = []
N = [0]


def check(cond, msg):
    N[0] += 1
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def rd(p):
    return open(p, encoding="utf-8").read()


def preprocess(text, cfg, tmp):
    sh = rd(os.path.join(HERE, "syntax_check.sh"))
    a = sh.index("\nINCS=(")
    b = sh.index("\nCONFIGS=(")
    src = os.path.join(FW, "application", "source", "usb", "_r108_usb_com.c")
    open(src, "w", encoding="utf-8").write(text)
    try:
        script = sh[a:b] + '\nexec gcc -E -P -std=gnu11 "${INCS[@]}" "${DEFS_%s[@]}" "$1"\n' % cfg
        r = subprocess.run(["bash", "-c", script, "pp", src], cwd=FW, capture_output=True, text=True)
    finally:
        os.unlink(src)
    if r.returncode != 0:
        check(False, "gcc -E (%s): %s" % (cfg, r.stderr[-300:]))
        return ""
    return r.stdout


def reboot_case_bodies(pp):
    """Тіла `case 0:` і `case 1:` внутрішнього switch(subCommand) 'C' 6 (препроцесований текст)."""
    i = pp.index("int subCommand")
    sw = pp[i:]
    j = sw.index("case 0:")
    k = sw.index("case 1:", j)
    m = sw.index("case 2:", k)
    return sw[j:k], sw[k:m]


def has_flush_before_reset(body):
    f = body.find("cpsFlushDeferredStores")
    r = body.find("NVIC_SystemReset")
    return f >= 0 and r >= 0 and f < r


def check_cfg(text, tag):
    """True, якщо в SMSF обидва шляхи з Flush до скидання."""
    with tempfile.TemporaryDirectory() as tmp:
        pp = preprocess(text, "SMSF", tmp)
        c0, c1 = reboot_case_bodies(pp)
        check(has_flush_before_reset(c0), "%s: 'C' 6 0 -- Flush до перезавантаження" % tag)
        check(has_flush_before_reset(c1), "%s: 'C' 6 1 -- Flush до перезавантаження" % tag)


HARNESS = r'''
#include <stdio.h>
#include <string.h>
static int lock = 1;                 /* всередині критичної секції CPS */
static char seq[64]; static int n;
static int bad;
#define TASK_LOCK_WRITE()   do { lock = 1; } while (0)
#define TASK_UNLOCK_WRITE() do { lock = 0; } while (0)
#define APRS_MSG1_UI 1
#define SMS_STORE_FLASH 1
void aprsMsgStoreFlush(void) { seq[n++] = 'A'; if (lock) bad++; }
void dmrSmsStoreFlush(void)  { seq[n++] = 'S'; if (lock) bad++; }
%s
int main(void)
{
	cpsFlushDeferredStores();
	seq[n] = 0;
	printf("%%s lock=%%d bad=%%d\n", seq, lock, bad);
	return 0;
}
'''


def run_helper(text, tmp, tag):
    a = text.index("static void cpsFlushDeferredStores(void)\n{")
    b = text.index("\n}\n", a) + 3
    fn = text[a:b]
    # прототипний рядок і #if навколо функції у файлі не потрібні -- гарнес визначає APRS_MSG1_UI/SMS_STORE_FLASH сам
    c = os.path.join(tmp, tag + ".c")
    open(c, "w", encoding="utf-8").write(HARNESS % fn)
    exe = os.path.join(tmp, tag)
    r = subprocess.run(["gcc", "-std=gnu11", "-o", exe, c], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-400:]
    p = subprocess.run([exe], capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


def main():
    if shutil.which("gcc") is None:
        print("ПРОПУСК: gcc нема -- test_r108flush не виконано (це не «пройдено»)")
        return 0
    usb = rd(USB)
    bp = rd(BP)
    # Ф1
    check_cfg(usb, "Ф1 SMSF")
    with tempfile.TemporaryDirectory() as tmp:
        for cfg in ("AES0", "AES1", "ENDATA"):
            pp = preprocess(usb, cfg, tmp)
            check("cpsFlushDeferredStores" not in pp, "Ф1: %s (без SMS_STORE_FLASH/APRS_MSG1_UI) -- коду дозапису нема" % cfg)
        # Ф2
        with tempfile.TemporaryDirectory() as t2:
            rc, out = run_helper(usb, t2, "h")
            check(rc == 0 and out == "AS lock=1 bad=0", "Ф2: порядок APRS->SMS, обидва без критичної секції, після -- знову в ній: %r" % (out,))
            # Ф3: те саме в powerDown
            m = re.findall(r"aprsMsgStoreFlush\(\);[^\n]*\n#endif\n#if defined\(SMS_STORE_FLASH\)\n\tdmrSmsStoreFlush\(\);", bp)
            check(len(m) == 2, "Ф3: у batteryAndPowerManagement.c APRS->SMS у двох місцях (%d)" % len(m))
            h = usb[usb.index("static void cpsFlushDeferredStores(void)\n{"):]
            h = h[:h.index("\n}\n")]
            check("#if defined(APRS_MSG1_UI)\n\taprsMsgStoreFlush();\n#endif\n#if defined(SMS_STORE_FLASH)\n\tdmrSmsStoreFlush();" in h,
                  "Ф3: порядок і #if у cpsFlushDeferredStores збігаються з powerDown")
            # Ф4: мутанти
            call = "\t\t\t\t\t\tcpsFlushDeferredStores();   // R108: відкладені SMS/APRS -- у флеш до перезавантаження\n"
            check(usb.count(call) == 2, "Ф4: два виклики знайдено для мутантів (%d)" % usb.count(call))
            first = usb.index(call)
            second = usb.index(call, first + 1)
            mut61 = usb[:second] + usb[second + len(call):]
            mut60 = usb[:first] + usb[first + len(call):]
            for name, txt in (("без Flush у 'C' 6 1", mut61), ("без Flush у 'C' 6 0", mut60)):
                saved = list(FAILS)
                n0 = N[0]
                import builtins
                p = builtins.print
                builtins.print = lambda *a, **k: None
                try:
                    check_cfg(txt, "мутант")
                finally:
                    builtins.print = p
                caught = len(FAILS) > len(saved)
                del FAILS[len(saved):]
                check(caught, "Ф4: мутант «%s» ловиться" % name)
            swapped = usb.replace("#if defined(APRS_MSG1_UI)\n\taprsMsgStoreFlush();\n#endif\n#if defined(SMS_STORE_FLASH)\n\tdmrSmsStoreFlush();\n#endif",
                                  "#if defined(SMS_STORE_FLASH)\n\tdmrSmsStoreFlush();\n#endif\n#if defined(APRS_MSG1_UI)\n\taprsMsgStoreFlush();\n#endif")
            check(swapped != usb, "Ф4: мутант «порядок SMS->APRS» застосовано")
            rc, out = run_helper(swapped, t2, "m_order")
            check(out != "AS lock=1 bad=0", "Ф4: мутант «порядок SMS->APRS» ловиться (%r)" % out)
            nolock = usb.replace("static void cpsFlushDeferredStores(void)\n{\n\tTASK_UNLOCK_WRITE();", "static void cpsFlushDeferredStores(void)\n{")
            check(nolock != usb, "Ф4: мутант «у критичній секції» застосовано")
            rc, out = run_helper(nolock, t2, "m_lock")
            check(out != "AS lock=1 bad=0", "Ф4: мутант «Flush у критичній секції» ловиться (%r)" % out)
    print("test_r108flush: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
