#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка, чи влазять українські підписи меню у рядок екрана.

ЩО САМЕ ОБМЕЖУЄ. Не пікселі. Пункт меню збирається як `snprintf(buf, SCREEN_LINE_BUFFER_SIZE,
"%s:%s", підпис, значення)`, а SCREEN_LINE_BUFFER_SIZE = 17 (uiGlobals.h:300), тобто
16 символів + NUL. Усе, що довше, snprintf МОВЧКИ обрізає -- без попередження й без
жодного сліду в коді. На екрані це виглядає як обірваний підпис (напр. "Настройка R"
замість "Настройка Rx"), і саме так це й помічають -- очима, на живій рації.

ДЖЕРЕЛО БЮДЖЕТУ. В english.h біля багатьох рядків стоїть коментар виду
`// MaxLen: 16 (with ':' + .on or .off)` -- це задум автора: скільки лишається на сам
підпис з урахуванням того, що додається праворуч. Скрипт бере саме ці числа, а не вигадує
свої, і додатково перевіряє реальні пари "підпис + значення", які видно в коді меню.

Кодування: ukrainian.h та інші *_ua.h -- cp1251, по одному байту на символ, тож довжина в
байтах дорівнює довжині в символах. Саме так їх бачить і прошивка.

Запуск:  python3 MDUV380_firmware/tools/check_menu_widths.py
Код виходу 1, якщо є переповнення -- можна ставити в CI.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, '..', 'application')
LANG = os.path.join(BASE, 'include', 'user_interface', 'languages')

LINE_CHARS = 16          # SCREEN_LINE_BUFFER_SIZE (17) - 1 на NUL


OUR_PLATFORM = 'PLATFORM_MDUV380'

# Пункти, де числове значення ЗАВІДОМО коротке, тож малий залишок місця -- не проблема.
# Тільки з обґрунтуванням: без нього це перетворюється на глушилку попереджень.
NUMERIC_OK = {
    'text_size': 'значення лише 1 або 2 (BIT_UI_USES_DOUBLE_HEIGHT), одна цифра',
}


def platform_gated_cases(src):
    """Множина міток case, які лежать під #if defined(PLATFORM_...) чужої платформи.

    Без цього перевірка репортує, напр., "Trackball:Високий" -- пункт, що збирається лише
    для MD2017 і на нашій рації не існує взагалі. Простий скан препроцесорних гілок:
    точний парсер тут не потрібен, бо в цих файлах гілки платформ не вкладені одна в одну.
    """
    gated, stack = set(), []
    for line in src.splitlines():
        s = line.strip()
        m = re.match(r'#\s*if\s+defined\(\s*(PLATFORM_\w+)\s*\)\s*$', s)
        if m:
            stack.append(m.group(1) != OUR_PLATFORM)
            continue
        if re.match(r'#\s*(else|elif)\b', s) and stack:
            stack[-1] = not stack[-1]
            continue
        if re.match(r'#\s*endif\b', s):
            if stack:
                stack.pop()
            continue
        cm = re.match(r'case\s+([A-Za-z_0-9]+)\s*:', s)
        if cm and any(stack):
            gated.add(cm.group(1))
    return gated


def load_strings(path, encoding):
    """Повертає {ключ: значення} з мовного файлу."""
    txt = open(path, 'rb').read().decode(encoding, errors='replace')
    return {m.group(1): m.group(2)
            for m in re.finditer(r'\.(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"', txt)}


def load_maxlen(path):
    """Повертає {ключ: (бюджет, текст_коментаря)} з коментарів // MaxLen: N у english.h."""
    out = {}
    for line in open(path, encoding='latin-1'):
        m = re.match(r'\s*\.(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"\s*,\s*//\s*Max[Ll]en:?\s*(\d+)(.*)', line)
        if m:
            out[m.group(1)] = (int(m.group(3)), m.group(4).strip())
    return out


en = load_strings(os.path.join(LANG, 'english.h'), 'latin-1')
ua = load_strings(os.path.join(LANG, 'ukrainian.h'), 'cp1251')
budget = load_maxlen(os.path.join(LANG, 'english.h'))

fails = []

# --- 1. Український рядок проти оголошеного бюджету --------------------------
print('=== 1. Підпис довший за оголошений MaxLen ===')
over = []
for key, (lim, note) in sorted(budget.items()):
    if key not in ua:
        continue
    n = len(ua[key])
    if n > lim:
        over.append((n - lim, key, ua[key], n, lim, en.get(key, ''), note))
for d, key, s, n, lim, e, note in sorted(over, key=lambda x: -x[0]):
    print(f'  +{d}  {key:32} "{s}" = {n} > {lim}   (en: "{e}") {note}')
print(f'  разом: {len(over)}')
fails += over

# --- 2. Реальні пари "підпис:значення" з коду меню ---------------------------
# Беремо лише те, що однозначно видно: leftSide = currentLanguage->X разом із
# rightSideConst = ... currentLanguage->Y у тому самому case-блоці.
print('\n=== 2. Пари "підпис:значення" довші за 16 символів ===')
pairs = []
seen = set()
files = sorted(glob.glob(os.path.join(BASE, 'source', 'user_interface', 'menu*.c')) +
               glob.glob(os.path.join(BASE, 'source', 'user_interface', 'ui*.c')))
for path in files:
    src = open(path, encoding='utf-8', errors='replace').read()
    gated = platform_gated_cases(src)
    parts = re.split(r'\n\s*case\s+([A-Za-z_0-9]+)\s*:', src)
    for cname, blk in zip(parts[1::2], parts[2::2]):
        if cname in gated:
            continue                       # пункт іншої платформи -- у нас його немає
        blk = blk[:2500]
        lm = re.search(r'leftSide\s*=\s*currentLanguage->(\w+)', blk)
        if not lm or lm.group(1) not in ua:
            continue
        label = ua[lm.group(1)]
        vals = set(re.findall(r'rightSideConst\s*=\s*[^;]*?currentLanguage->(\w+)', blk))
        for am in re.finditer(r'const\s+char\s*\*\s*\w+\s*\[\s*\]\s*=\s*\{([^}]*)\}', blk):
            vals |= set(re.findall(r'currentLanguage->(\w+)', am.group(1)))
        cand = [(v, ua[v]) for v in vals if v in ua]
        if not cand:
            continue
        vkey, vtext = max(cand, key=lambda kv: len(kv[1]))
        total = len(label) + 1 + len(vtext)
        k = (lm.group(1), vkey)
        if total > LINE_CHARS and k not in seen:
            seen.add(k)
            pairs.append((total - LINE_CHARS, os.path.basename(path), lm.group(1), vkey,
                          f'{label}:{vtext}', total))
for d, f, lk, vk, line, total in sorted(pairs, key=lambda x: -x[0]):
    print(f'  +{d}  {f:26} {lk}/{vk}')
    print(f'        "{line}" = {total} > {LINE_CHARS}')
print(f'  разом: {len(pairs)}')
fails += pairs

# --- 3. Пункти з ЧИСЛОВИМ значенням ------------------------------------------
# Саме тут ховався реальний дефект: "Рівень потуж." (13) + ':' + "250" = 17 -> snprintf
# обрізав до 16, і оператор бачив ЗНАЧЕННЯ 25 замість 250. Частини 1 і 2 такого не ловлять:
# бюджет MaxLen у english.h стоїть не скрізь, а значення тут не з мовної таблиці, а з
# snprintf(rightSideVar, ...).
#
# Рахуємо ТОЧНО ту частину, яку можна порахувати: довжину літеральних шматків формату.
# Далі показуємо, скільки СИМВОЛІВ ЛИШАЄТЬСЯ на самі цифри. Менш ніж 3 -- підозріло:
# більшість числових налаштувань рації доходять до трьох цифр (0..255, потужність 250 мВт,
# кути, відсотки), а від'ємні -- до чотирьох.
MIN_DIGITS = 3

print('\n=== 3. Скільки місця лишається на числове значення ===')
tight = []
seen3 = set()
for path in files:
    src = open(path, encoding='utf-8', errors='replace').read()
    gated = platform_gated_cases(src)
    parts = re.split(r'\n\s*case\s+([A-Za-z_0-9]+)\s*:', src)
    for cname, blk in zip(parts[1::2], parts[2::2]):
        if cname in gated:
            continue
        blk = blk[:2500]
        lm = re.search(r'leftSide\s*=\s*currentLanguage->(\w+)', blk)
        sm = re.search(r'snprintf\(\s*rightSideVar\s*,[^,]+,\s*"((?:[^"\\]|\\.)*)"', blk)
        if not lm or not sm or lm.group(1) not in ua or lm.group(1) in NUMERIC_OK:
            continue
        fmt = sm.group(1)
        convs = re.findall(r'%[-+ #0]*\d*(?:\.\d+)*[a-zA-Z]', fmt)
        if any(c.endswith('s') for c in convs):
            continue                      # ширина рядкового аргументу тут невідома
        # "%%" друкується як ОДИН символ '%'. Без цієї заміни воно рахувалося за два, і
        # перевірка давала хибну тривогу на кожному пункті з відсотками (яскравість, шумодав).
        literal = re.sub(r'%[-+ #0]*\d*(?:\.\d+)*[a-zA-Z]', '', fmt).replace('%%', '%')
        # %03u тощо мають власну мінімальну ширину -- враховуємо її як уже зайняту
        fixed = sum(int(m) for m in re.findall(r'%[-+ #0]*(\d+)[a-zA-Z]', fmt))
        label = ua[lm.group(1)]
        left = LINE_CHARS - len(label) - 1 - len(literal) - fixed
        free_convs = len(convs) - len(re.findall(r'%[-+ #0]*\d+[a-zA-Z]', fmt))
        if free_convs <= 0:
            continue
        k = (lm.group(1), fmt)
        if left < MIN_DIGITS and k not in seen3:
            seen3.add(k)
            tight.append((left, os.path.basename(path), lm.group(1), label, fmt))
for left, f, key, label, fmt in sorted(tight, key=lambda x: x[0]):
    print(f'  {left:>2} символ(ів) на цифри  {f:26} {key}')
    print(f'        "{label}:" + формат "{fmt}"')
print(f'  разом підозрілих: {len(tight)}')
fails += tight

# ---------------------------------------------------------------------------
# 4. ПІКСЕЛЬНА ширина рядків, які малюються НЕ через меню-список.
#
# Розділи 1--3 рахують СИМВОЛИ, бо там межа -- SCREEN_LINE_BUFFER_SIZE. Але підказки й
# банери всередині екранів малюються напряму (displayPrintCentered/displayPrintAt), і там
# межа інша -- ПІКСЕЛІ. displayPrintCore обрізає рядок так само мовчки:
#
#     if ((charWidthPixels * sLen) + xPos > DISPLAY_SIZE_X)
#             sLen = (DISPLAY_SIZE_X - xPos) / charWidthPixels;
#
# Реальний випадок, який це знайшло: RCFG_HINT був 34 символи при FONT_SIZE_1 (6 px) на
# екрані 160 px -> на рації було видно рівно 26 символів, "L/R:зміна GRN:зберегти RED",
# і саме пояснення про скасування зникало.
#
# Рядки з '%' пропускаємо: довжина аргументу тут невідома, це вже робота розділу 3.
# Обмеження: аргументи виклику ріжуться по комі, тож літерал із комою всередині просто
# не розпізнається (хибних тривог це не дає -- лише пропуск).
FONT_W = {
    'FONT_SIZE_1': 6, 'FONT_SIZE_1_BOLD': 6, 'FONT_SIZE_2': 8,
    'FONT_SIZE_3': 8, 'FONT_SIZE_4': 16,
}
DISPLAY_SIZE_X = 160          # 128 + DISPLAY_H_EXTRA_PIXELS(32), uiGlobals.h для MDUV380

print('\n=== 4. Піксельна ширина підказок і банерів (displayPrintCentered/At) ===')

# Значення макросів: наші cp1251-заголовки + локальні #define всередині самих .c
macros = {}
for path in glob.glob(os.path.join(LANG, '*.h')):
    raw = open(path, 'rb').read()
    try:
        txt = raw.decode('cp1251')
    except UnicodeDecodeError:
        txt = raw.decode('utf-8', 'replace')
    for m in re.finditer(r'#\s*define\s+(\w+)\s+"((?:[^"\\]|\\.)*)"', txt):
        macros.setdefault(m.group(1), set()).add(m.group(2))

UI = os.path.join(BASE, 'source', 'user_interface')
wide = []
for path in sorted(glob.glob(os.path.join(UI, '*.c'))):
    raw = open(path, 'rb').read()
    try:
        src = raw.decode('cp1251')
    except UnicodeDecodeError:
        src = raw.decode('utf-8', 'replace')
    local = {}
    for m in re.finditer(r'#\s*define\s+(\w+)\s+"((?:[^"\\]|\\.)*)"', src):
        local.setdefault(m.group(1), set()).add(m.group(2))

    call = re.compile(r'displayPrint(?:Centered|At)\s*\(([^;]*?)\)\s*;', re.S)
    for m in call.finditer(src):
        args = [a.strip() for a in m.group(1).split(',')]
        font = next((a for a in args if a in FONT_W), None)
        if font is None:
            continue
        # текстовий аргумент -- передостанній перед вирівнюванням/шрифтом
        idx = args.index(font)
        if idx < 1:
            continue
        arg = args[idx - 1]
        cands = set()
        lit = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', arg)
        if lit:
            cands.add(lit.group(1))
        else:
            cands |= local.get(arg, set()) | macros.get(arg, set())
        for text in cands:
            if '%' in text:
                continue
            px = FONT_W[font] * len(text)
            if px > DISPLAY_SIZE_X:
                wide.append((px, os.path.basename(path), arg, font, text))

for px, f, arg, font, text in sorted(wide, key=lambda x: -x[0]):
    fits = DISPLAY_SIZE_X // FONT_W[font]
    print(f'  {px:>4} px > {DISPLAY_SIZE_X}  {f:26} {arg} ({font})')
    print(f'        "{text}"  -> буде видно лише "{text[:fits]}"')
print(f'  разом задовгих: {len(wide)}')
fails += wide

# ---------------------------------------------------------------------------
# 5. ui7: пункти SMS у стокових меню «Налаштувань» (menuRadioOptions.c, menuDisplayOptions.c).
#    Підпис там -- не currentLanguage, а MSGS_SET_* (messages_ua.h, cp1251; англійські -- #else у
#    .c), тож частина 2 їх не бачить. Рядок той самий: snprintf("%s:%s", ...) у 17-байтовий буфер.
print('\n=== 5. Пункти SMS у «Налаштуваннях» (MSGS_SET_*) ===')
sms_over = []
ua_msgs = {m.group(1): m.group(2) for m in re.finditer(
    r'#define\s+(MSGS_SET_\w+)\s+"((?:[^"\\]|\\.)*)"',
    open(os.path.join(LANG, 'messages_ua.h'), 'rb').read().decode('cp1251'))}
en_msgs = {}
for fn in ('menuRadioOptions.c', 'menuDisplayOptions.c'):
    src = open(os.path.join(BASE, 'source', 'user_interface', fn), encoding='utf-8').read()
    en_msgs.update({m.group(1): m.group(2) for m in re.finditer(
        r'#define\s+(MSGS_SET_\w+)\s+"((?:[^"\\]|\\.)*)"', src)})
SMS_ITEMS = [   # (підпис, можливі значення: ключі MSGS_SET_* або 'on'/'off' з мовної таблиці)
    ('MSGS_SET_MONITOR', ['on', 'off']),
    ('MSGS_SET_TXCONF',  ['on', 'off', 'MSGS_SET_TX_R12']),
    ('MSGS_SET_FONT',    ['MSGS_SET_FONT_BIG', 'MSGS_SET_FONT_SMALL']),
]
for lang, msgs, table in (('UA', ua_msgs, ua), ('EN', en_msgs, en)):
    for lab, vals in SMS_ITEMS:
        if lab not in msgs:
            sms_over.append((lang, lab, 'немає визначення', 0))
            continue
        for v in vals:
            vt = msgs.get(v) if v.startswith('MSGS_') else table.get(v)
            if vt is None:
                sms_over.append((lang, lab, f'немає {v}', 0))
                continue
            line = f'{msgs[lab]}:{vt}'
            if len(line) > LINE_CHARS:
                sms_over.append((lang, lab, line, len(line)))
for lang, lab, line, n in sms_over:
    print(f'  {lang} {lab}: "{line}" = {n} > {LINE_CHARS}')
print(f'  разом: {len(sms_over)}')
fails += sms_over

print('\n=== 6. Екран «APRS станції», банер і пункти меню «APRS» (languages/aprsrx_ua.h, R8 / R8-fix) ===')
# Рядок екрана FONT_SIZE_1 -- 6 px на символ, екран 160 px => 26 символів; пункт меню -- 16
# (SCREEN_LINE_BUFFER_SIZE); рядок банера -- 16. Для шаблонів з %s/%u/%lu підставляємо НАЙГІРШЕ значення.
aprs_over = []
aprs_path = os.path.join(LANG, 'aprsrx_ua.h')
if os.path.exists(aprs_path):
    aprs = {m.group(1): m.group(2) for m in re.finditer(
        r'#define\s+(APRSRX_\w+)\s+"((?:[^"\\]|\\.)*)"', open(aprs_path, 'rb').read().decode('cp1251'))}
    WORST_S = {   # що підставляється замість %s (найдовше можливе)
        'APRSRX_STATUS_FMT': ['Слухаю'],
        'APRSRX_CARD_POS': ['-179.1234 -179.1234'],
        'APRSRX_CARD_DIST': ['20000' + aprs.get('APRSRX_KM', '') + ' NW'],
        'APRSRX_CARD_LAST': ['59' + 'хв'],
        'APRSRX_CARD_PATH': ['W' * 20],
        'APRSRX_CARD_TYPE': [aprs.get('APRSRX_T_MSG', '')],
        'APRSRX_BANNER_FMT': ['UW5ELK-15', '20000' + aprs.get('APRSRX_KM', '') + ' NW'],
    }
    SKIP = {'APRSRX_MSG_NOTE_FMT', 'APRSRX_M', 'APRSRX_KM'}   # нотатка йде на повнекранну картку (перенос по словах)
    for name, val in aprs.items():
        if name in SKIP:
            continue
        if name == 'APRSRX_BANNER_FMT':
            # два рядки банера, роздільник \n
            l1, l2 = val.split('\\n')
            for call in ('UW5ELK-15',):
                a = l1.replace('%s', call)
                b = l2.replace('%s', '20000' + aprs.get('APRSRX_KM', '') + ' NW')
                for t in (a, b):
                    if len(t) > LINE_CHARS:
                        aprs_over.append((name, t, len(t), LINE_CHARS))
            continue
        limit = LINE_CHARS if name in ('APRSRX_TITLE', 'APRSRX_DIAG_TITLE', 'APRSRX_DIAG2_TITLE', 'APRSRX_HUB_SETTINGS', 'APRSRX_HUB_PROBE') else 26
        t = val
        subs = WORST_S.get(name)
        for rx, rep in (('%lu', '99999'), ('%u', '65535')):
            t = t.replace(rx, rep)
        if '%s' in t:
            t = t.replace('%s', subs[0] if subs else 'XXXXXXXXXXXXXXX')
        if len(t) > limit:
            aprs_over.append((name, t, len(t), limit))
    # шапка списку у стані «Запуск...» з причиною: найдовша причина
    why = [aprs[k] for k in aprs if k.startswith('APRSRX_OFF_')]
    t = aprs.get('APRSRX_WAITING', '') + ' ' + max(why, key=len)
    if len(t) > 26:
        aprs_over.append(('APRSRX_WAITING+причина', t, len(t), 26))
    # рядок списку: маркер(1) + позивний(9) + відстань(10) + вік(5)
    if 1 + 9 + 10 + 5 > 26:
        aprs_over.append(('рядок списку', '', 25, 26))
for name, t, n, lim in aprs_over:
    print(f'  {name}: "{t}" = {n} > {lim}')
print(f'  разом: {len(aprs_over)}')
fails += aprs_over

print('\n=== 7. «Режим APRS»: екран, налаштування, редактор, сповіщення (languages/aprsmode_ua.h, R10) ===')
# Рядок екрана FONT_SIZE_1 -- 26 символів; заголовок -- 16; значення поля налаштувань -- 15 (26 - маркер - мітка(9) - пробіл);
# мітка поля -- 9; рядок сповіщення -- 16. Для шаблонів підставляємо НАЙГІРШЕ значення.
mode_over = []
mode_path = os.path.join(LANG, 'aprsmode_ua.h')
if os.path.exists(mode_path):
    am = {m.group(1): m.group(2) for m in re.finditer(
        r'#define\s+(APRSM_\w+)\s+"((?:[^"\\]|\\.)*)"', open(mode_path, 'rb').read().decode('cp1251'))}
    states = [am[k] for k in am if k.startswith('APRSM_M_ST_') or k.startswith('APRSM_ERR_')]
    WORST_S = {
        'APRSM_M_FREQ': '430.0750',
        'APRSM_M_STATE': max(states, key=len),
        'APRSM_M_FORMAT': '255',
        'APRSM_M_BEACONS': '99д',
        'APRSM_E_NOW': '-179.123456',
        'APRSM_E_MODE': 'абв',
        'APRSM_V_FREQ': '430.0750',
        'APRSM_V_PATH_FMT': 'WIDE22',
        'APRSM_V_CALL_FMT': 'UW5ELK',
    }
    def worst(name, val):
        t = val.replace('%%', '\x01')
        t = re.sub(r'%\.(\d+)s', lambda m_: 'X' * int(m_.group(1)), t)   # «%.9s» -- рівно стільки символів (R11-fix: і для APRSM_M_3P)
        t = t.replace('%02u', '59').replace('%lu', '99999').replace('%d', '-120').replace('%c', '*').replace('%u', '65535')
        if name == 'APRSM_TITLE_FMT':
            t = val.replace('%u', '3')
        if name == 'APRSM_M_FORMAT':
            t = val.replace('%u', '16')   # станцій: не більше 16
        if '%s' in t:
            t = t.replace('%s', WORST_S.get(name, 'XXXXXXXXXXXXXXX'))
        return t.replace('\x01', '%')
    for name, val in am.items():
        t = worst(name, val).replace('\\\\', '\\')
        if name == 'APRSM_TITLE_FMT' or name == 'APRSM_MENU':
            lim = LINE_CHARS
        elif name.startswith('APRSM_L_'):
            lim = 9
        elif name.startswith('APRSM_V_'):
            if name == 'APRSM_V_INT_FMT':
                t = val.replace('%u', '60')
            if name == 'APRSM_V_SQL_FMT':
                t = val.replace('%u', '100').replace('%%', '%')
            lim = 15
        elif name.startswith('APRSM_ERR_') or name == 'APRSM_NOT_NOW':
            lim = LINE_CHARS
        elif name.startswith('APRSM_SYM_'):
            lim = 13   # значення поля «Код сим.»: знак + пробіл + назва = 15 символів
        else:
            lim = 26
        if len(t) > lim:
            mode_over.append((name, t, len(t), lim))
    # імена символів: у рядку «Код сим.» -- знак, пробіл, назва: 15 символів значення
    # рядок налаштувань: маркер(1) + мітка(9) + пробіл(1) + значення(15) = 26
    if 1 + 9 + 1 + 15 > 26:
        mode_over.append(('рядок налаштувань', '', 26, 26))
for name, t, n, lim in mode_over:
    print(f'  {name}: "{t}" = {n} > {lim}')
print(f'  разом: {len(mode_over)}')
fails += mode_over

print('\n=== 8. «Повідомлення APRS»: список, читання, набір, сповіщення (languages/aprsmsg_ua.h, R11) ===')
# Рядок екрана FONT_SIZE_1 -- 26 символів; заголовок і пункт меню -- 16; рядок сповіщення -- 16;
# слово стану в рядку списку -- 9. Для шаблонів підставляємо НАЙГІРШЕ значення.
msg_over = []
msg_path = os.path.join(LANG, 'aprsmsg_ua.h')
if os.path.exists(msg_path):
    mm = {m.group(1): m.group(2) for m in re.finditer(
        r'#define\s+(APRSMSG_\w+)\s+"((?:[^"\\]|\\.)*)"', open(msg_path, 'rb').read().decode('cp1251'))}
    for name, val in mm.items():
        t = val.replace('%u', '99').replace('%s', 'UW5ELK-15')   # лічильники: список ≤ 8, черга ≤ 4, байтів ≤ 67
        if name == 'APRSMSG_K_TITLE':
            t = val.replace('%s', 'ABC')   # R11-fix2: заголовок шпаргалки -- мітка режиму multitap (smsMtModeLabel(), до 3 символів)
        if name.startswith('APRSMSG_MENU') or name.startswith('APRSMSG_TITLE') or name.startswith('APRSMSG_E_') or name == 'APRSMSG_K_TITLE':
            lim = LINE_CHARS
        elif name.startswith('APRSMSG_ST_'):
            lim = 9
        else:
            lim = 26
        if len(t) > lim:
            msg_over.append((name, t, len(t), lim))
    # рядок списку: маркер(1) + мітка(1) + позивний(9) + пробіл(1) + текст/статус(9) + вік(5) = 26
    if 1 + 1 + 9 + 1 + 9 + 5 > 26:
        msg_over.append(('рядок списку', '', 26, 26))
for name, t, n, lim in msg_over:
    print(f'  {name}: "{t}" = {n} > {lim}')
print(f'  разом: {len(msg_over)}')
fails += msg_over

print(f'\n{"Є ПЕРЕПОВНЕННЯ" if fails else "Переповнень не знайдено"} (всього: {len(fails)})')
sys.exit(1 if fails else 0)
