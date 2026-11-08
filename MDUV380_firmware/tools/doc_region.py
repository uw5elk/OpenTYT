# -*- coding: utf-8 -*-
"""R75: малі блоки налаштувань (custom-data) як частина ДОКУМЕНТА кодплага. Без Tk і без рації.

Область custom-data (сирий флеш 0x20000..0x2FFFF, 64 КБ) лежить поза кодплагом, і раніше панелі «бікон/шумодав», «RCTL», «Роумінг» писали
в неї НЕГАЙНО, кожна своїм кнопкою. Тепер документ тримає копію області, а ці панелі лише правлять у ній блоки (через RegionStore, який
поводиться як custom_data.read_block/write_block, але над байтами). У рацію зміни йдуть однією дією «Записати в рацію» (doc_actions).

Що входить у документ (DOC_TYPES) і чому саме це:
  9 RCTL_CONFIG, 13 APRS_MODE_CFG, 14 APRS_BEACON_CFG, 15 ROAM_CFG, 16 ROAM_NAMES -- малі блоки НАЛАШТУВАНЬ з фіксованою довжиною, які
  пише лише CPS/CHIRP/прошивка при зміні меню; їх безпечно писати разом із кодплагом (однакова довжина, sector-safe групове стирання,
  звірка читанням, страхова копія області).
Що НЕ входить (лишається в групі «Сервіс», зі своїми кнопками):
  AES (тип 6 і таблиця ключів 0xD9F9C..) -- секретні дані; теми (4, 5), заставка (1), мелодія (2), супутники (3) -- великі області й
  окремі формати; SMS (7, 8, 12) і лічильники RCTL (10) і «переслухати» (11) -- пише прошивка під час роботи (стан), CPS їх не веде.
Блок пишеться в рацію лише якщо його вміст у документі відрізняється від того, що документ прочитав із рації («база»): так застарілий
образ не затирає зміни, які рація зробила сама, а блоки поза DOC_TYPES не пишуться НІКОЛИ (навіть якщо вони є в файлі документа).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cps_link as cl  # noqa: E402
import custom_region as cr  # noqa: E402

TYPE_RCTL_CONFIG = 9
TYPE_APRS_MODE_CFG = 13
TYPE_APRS_BEACON_CFG = 14
TYPE_ROAM_CFG = 15
TYPE_ROAM_NAMES = 16

DOC_TYPES = (TYPE_RCTL_CONFIG, TYPE_APRS_MODE_CFG, TYPE_APRS_BEACON_CFG, TYPE_ROAM_CFG, TYPE_ROAM_NAMES)

# Назви для діалогу «що зміниться»: у термінах користувача, без внутрішніх назв блоків.
DOC_TITLES = {
    TYPE_RCTL_CONFIG: "Віддалене керування (RCTL)",
    TYPE_APRS_MODE_CFG: "APRS: шумодав приймача",
    TYPE_APRS_BEACON_CFG: "APRS: стоковий бікон",
    TYPE_ROAM_CFG: "Роумінг: налаштування",
    TYPE_ROAM_NAMES: "Роумінг: імена списків",
}

# Типи, яких у «Записати в рацію» немає за жодних умов (захист від помилки в списку вище; перевіряє тест).
NEVER_TYPES = (6, 10)         # AES_KEYS (секретне) і RCTL_STATE (лічильники прошивки)


class RegionStore:
    """Область custom-data в пам'яті. Інтерфейс read_block/write_block збігається з custom_data (перший аргумент `ser` ігнорується),
    тож код панелей/модулів (aprs_beacon_cfg, roam_cfg) працює з ним без змін логіки."""

    def __init__(self, data):
        if len(data) != cr.REGION_LEN:
            raise cl.CpsError("область налаштувань має %d Б, а має бути %d" % (len(data), cr.REGION_LEN))
        self.buf = bytearray(data)
        if all(x == 0xFF for x in self.buf[:cr.REGION_HDR]):
            # у рації області ще нема: в документі створюємо лише заголовок (у рацію він піде планом як header_needed)
            self.buf[:cr.REGION_HDR] = cr.MAGIC + b"\x00" * 4

    def data(self):
        return bytes(self.buf)

    def read_block(self, _ser, data_type, max_len):
        b = cr.parse_region(bytes(self.buf)).by_type().get(data_type)
        return None if b is None else b.payload[:max_len]

    def write_block(self, _ser, data_type, payload):
        if data_type not in DOC_TYPES:
            return False, "блок типу %d не входить до документа" % data_type
        return cr.simulate_write(self.buf, data_type, bytes(payload))


def redact_secrets(data):
    """Копія області для ФАЙЛА документа без секретів: у блоці AES_KEYS (тип 6), якщо в ньому є ключовий матеріал (слот valid=1 з ненульовим
    ключем, лишок старих версій), усе після 8-байтового заголовка 'AESK' обнуляється -- довжина блока й розкладка області не змінюються. Ключі AES
    не потрапляють у файл документа за жодних умов; вони -- лише в «Сервіс» (AES-ключі, бекап з окремим прапорцем).
    Повертає (bytes, True|False -- чи щось обнулено)."""
    reg = cr.parse_region(bytes(data))
    buf = bytearray(data)
    hit = False
    for b in reg.blocks:
        if b.type == cr.TYPE_AES_KEYS and b.secret:
            a = b.offset + cr.BLOCK_HDR
            buf[a + 8:a + len(b.payload)] = b"\x00" * (len(b.payload) - 8)
            hit = True
    return bytes(buf), hit


def block_map(data):
    """{тип: вміст} для типів документа (з байтів області; порожньо, якщо заголовка нема)."""
    reg = cr.parse_region(bytes(data))
    return {b.type: b.payload for b in reg.blocks if b.type in DOC_TYPES} if reg.magic_ok else {}


def outside_unchanged(old, new):
    """True, якщо поза блоками документа область не змінилась: заголовок, і кожен блок, що не з DOC_TYPES, лишився на тому самому місці
    з тими самими байтами (нові блоки документа можуть з'явитись лише у вільному хвості, а наявні -- змінитись на місці)."""
    ro, rn = cr.parse_region(bytes(old)), cr.parse_region(bytes(new))
    if not (ro.magic_ok and rn.magic_ok) or bytes(old)[:cr.REGION_HDR] != bytes(new)[:cr.REGION_HDR]:
        return False
    def other(r):
        return {(b.type, b.offset, b.payload) for b in r.blocks if b.type not in DOC_TYPES}
    if other(ro) != other(rn):
        return False
    # байти поза розібраною частиною (хвіст після останнього блока) теж не мають змінюватись, окрім вільного місця під нові блоки
    tail_o, tail_n = bytes(old)[rn.end:], bytes(new)[rn.end:]
    return tail_o == tail_n if rn.end >= ro.end else False


def changed_types(base, cur):
    """Типи документа, чий вміст у `cur` відрізняється від `base` (або з'явився/зник)."""
    bm, cm = block_map(base), block_map(cur)
    return [t for t in DOC_TYPES if bm.get(t) != cm.get(t) and t in cm]


def doc_blocks(cur, only_types=None):
    """[custom_region.Block] типів документа, що є в `cur` (лише DOC_TYPES); only_types звужує."""
    reg = cr.parse_region(bytes(cur))
    return [b for b in reg.blocks if b.type in DOC_TYPES and (only_types is None or b.type in only_types)]


def plan_for_radio(blocks, radio_region):
    """План запису блоків у ПОТОЧНУ область рації. Нічого не пише. RegionError, якщо область рації чужа (не стерта й без заголовка).
    selected = рівно типи з blocks, тож AES/стан/інше не потрапляють у план за жодних умов."""
    types = set(b.type for b in blocks)
    assert not (types & set(NEVER_TYPES)), "заборонений тип у плані запису"
    return cr.plan_blocks(blocks, cr.parse_region(radio_region), selected=types)


def plan_text(plan):
    """Текст плану словами користувача (назви розділів, а не внутрішні назви блоків)."""
    lines = []
    for it in plan.items:
        line = "  %s -- %s" % (DOC_TITLES.get(it.block.type, it.block.title), cr.STATUS_TEXT[it.status])
        if it.note:
            line += ": " + it.note
        lines.append(line)
    return "\n".join(lines)


def plan_lines(plan):
    """Рядки для діалогу «що зміниться»: лише блоки, які справді будуть записані або відмовлені."""
    out = []
    for it in plan.items:
        t = DOC_TITLES.get(it.block.type, it.block.title)
        if it.status == cr.ST_OVERWRITE:
            out.append(("changed", "Налаштування", "%s: буде змінено" % t))
        elif it.status == cr.ST_CREATE:
            out.append(("added", "Налаштування", "%s: буде створено в рації" % t))
        elif it.status == cr.ST_REFUSED:
            out.append(("removed", "Налаштування", "%s: ЗАПИСАТИ НЕ МОЖНА -- %s" % (t, it.note)))
    return out


def save_safety(radio_region, out_dir, now=None):
    """Страхова копія поточної області налаштувань рації у файл (перевіряється читанням). RegionError = нічого не записувати."""
    if not os.access(out_dir, os.W_OK):
        raise cr.RegionError("нема права писати в теку %s, де має лежати страхова копія області налаштувань. Нічого не записано." % out_dir)
    safety = cl.unique_path(out_dir, cl.timestamp_name("customdata_pre-write", ".bin", now))
    try:
        with open(safety, "xb") as f:
            f.write(radio_region)
        with open(safety, "rb") as f:
            if f.read() != radio_region:
                raise OSError("записаний файл відрізняється від прочитаного")
    except OSError as e:
        try:
            os.unlink(safety)
        except OSError:
            pass
        raise cr.RegionError("не вдалося зберегти страхову копію області налаштувань (%s). Нічого не записано." % e)
    return safety


def write_region(link, plan, radio_region, safety=None, out_dir=None, log=print, progress=None, now=None, post_reset=True):
    """Записати план в область рації. Порядок безпеки: страхова копія поточної області (перевірена; `safety` -- вже зроблена викликачем
    ДО будь-якого запису, інакше робиться тут) -> apply_plan (групи по секторах, custom_data sector-safe, звірка кожного блока читанням)
    -> звірка всієї області з очікуваною -> (за потреби) C 6 1. Повертає {written, text, safetyCopy, regionMatchesExpected, failed}."""
    if not plan.writes():
        return {"written": [], "text": "Налаштування в рації вже такі самі -- записувати нічого.", "safetyCopy": safety, "failed": None,
                "regionMatchesExpected": True}
    if safety is None:
        safety = save_safety(radio_region, out_dir or os.getcwd(), now)
    log("Страхова копія області налаштувань: %s" % safety)
    res = cr.apply_plan(link, plan, log, progress)
    text = cr.result_text(res)
    matches = None
    if not res["failed"]:
        matches = cr.read_radio_region(link) == cr.expected_region(radio_region, plan)
        if not matches:
            text += "\nУВАГА: після запису область у рації не збігається з очікуваною (поза записаними блоками щось відрізняється)."
    if post_reset and res["written"]:
        import cps_restore
        cps_restore._send_c(link, 6, cps_restore.POST_RESTORE_SUB)
    return {"written": res["written"], "text": text, "safetyCopy": safety, "failed": res["failed"], "regionMatchesExpected": matches,
            "result": res}
