# -*- coding: utf-8 -*-
"""R35, частина B: картинка заставки (custom-data блок IMAGE = тип 1).

ФОРМАТ -- ЛИШЕ З КОДУ ПРОШИВКИ (user_interface/uiSplashScreen.c updateScreen(), hardware/HX8353E_display.c displayConvertGD77ImageData()).
БРИФ ПРИПУСКАВ СИРИЙ RGB565 160x128 (40960 Б) -- ЦЕ НЕ ТАК. Прошивка очікує МОНОХРОМНУ картинку формату GD77:

  * 128 x 64 точок, 1 біт на точку = 1024 байти (8 «сторінок» по 128 байтів);
  * байт[ сторінка*128 + x ], біт r (r = 0 -- молодший) -- це точка (x, сторінка*8 + r);
  * біт 1 = колір ТЛА заставки (THEME_ITEM_BG_SPLASHSCREEN), біт 0 = колір переднього плану (THEME_ITEM_FG_SPLASHSCREEN) -- саме так, а не навпаки
    (`((d >> r) & 1) ? backgroundColour : foregroundColour`);
  * картинка малюється на екрані 160x128 зі зміщенням (x=16, y=32): startOffset = 32*160 + (160-128)/2; решта екрана -- колір тла заставки;
  * кольори беруться з поточної теми (displayThemeApply(FG_SPLASHSCREEN, BG_SPLASHSCREEN)), тож один і той самий блок виглядає по-різному в денній і нічній темах;
  * читання обмежене розміром кадрового буфера (40960 Б), але використовуються лише перші 1024 Б блока. Блок коротший за 1024 Б лишив би кінець картинки зі
    сміттям (буфер перед читанням заливається кольором тла, але читання заливає лише len байтів) -- такі блоки ми НЕ пишемо;
  * блок показується, коли EEPROM 0x7518 == 0 («тип екрана привітання = картинка») І блок IMAGE є; якщо блока нема, малюється текст (в українській збірці --
    гасло) НЕЗАЛЕЖНО від байта 0x7518. Тому «Прибрати картинку» = вилучити блок (custom_data.retire_block); байт 0x7518 міняти не потрібно.
  * Довжину наявного блока міняти не можна (codeplugSetOpenGD77CustomData): якщо в рації вже є IMAGE іншої довжини, ніж 1024, запис відмовляє.

Модуль без Tk: декодери PNG (усі типи, 1..16 біт, Adam7), BMP (1/4/8/24/32 біти, без стиснення) і PBM/PGM/PPM -- на zlib/struct, без Pillow. JPEG без бібліотеки
не читається -- про це сказано користувачу. Зменшення -- усереднення за площею; способи вписування -- «вписати / заповнити / розтягнути»; квантування до 1 біта --
поріг, Флойд-Штейнберг, упорядковане (Баєр 4x4). Передпоказ малюється рендером екрана з «Тем» (screen_sim), тобто ТАКИМИ Ж кольорами теми, як на рації."""
import struct
import zlib

BLOCK_TYPE = 1                    # CODEPLUG_CUSTOM_DATA_TYPE_IMAGE
W, H = 128, 64
BLOCK_LEN = W * H // 8            # 1024
SCREEN_W, SCREEN_H = 160, 128
OFFSET_X, OFFSET_Y = (SCREEN_W - W) // 2, 32      # displayConvertGD77ImageData: startOffset = (32 * DISPLAY_SIZE_X) + (DISPLAY_SIZE_X - 128) / 2
MAX_PIXELS = 24 * 1000 * 1000     # вище -- відмова (чисто-питоновий декодер)

FIT_MODES = (("fit", "Вписати (з полями)"), ("fill", "Заповнити (з обрізанням)"), ("stretch", "Розтягнути"))
QUANT_MODES = (("threshold", "Поріг"), ("dither", "Флойд-Штейнберг"), ("bayer", "Упорядковане (Баєр 4x4)"))


class ImageError(ValueError):
    """Файл не вдалося прочитати як картинку (пояснення словами)."""


# ---------------------------------------------------------------------------------------------------------------------------------
#  Декодери -> градації сірого
# ---------------------------------------------------------------------------------------------------------------------------------

class Gray:
    """Картинка в градаціях сірого 0..255; прозорість уже змішана з тлом (transparent_to)."""

    def __init__(self, w, h, data):
        if len(data) != w * h:
            raise ImageError("внутрішня помилка: розмір даних не збігається")
        self.w, self.h, self.data = w, h, data


def _lum(r, g, b):
    return (299 * r + 587 * g + 114 * b + 500) // 1000


def _over(v, a, bg):
    """Колір v з прозорістю a (0..255) поверх тла bg."""
    if a >= 255:
        return v
    return (v * a + bg * (255 - a) + 127) // 255


def decode(data, transparent_to=255):
    """Байти файла -> Gray. Формат визначається за сигнатурою."""
    data = bytes(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return decode_png(data, transparent_to)
    if data[:2] == b"BM":
        return decode_bmp(data, transparent_to)
    if data[:1] == b"P" and data[1:2] in b"123456":
        return decode_pnm(data)
    if data[:3] == b"\xff\xd8\xff":
        raise ImageError("JPEG без зовнішньої бібліотеки (Pillow) не читається -- збережіть картинку як PNG або BMP і відкрийте її")
    if data[:4] in (b"GIF8",):
        raise ImageError("GIF не підтримується -- збережіть картинку як PNG або BMP")
    raise ImageError("невідомий формат файла (потрібен PNG, BMP або PBM/PGM/PPM)")


def decode_file(path, transparent_to=255):
    with open(path, "rb") as f:
        return decode(f.read(), transparent_to)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, pos, rows, rowbytes, bpp):
    """Знімає PNG-фільтри з `rows` рядків по `rowbytes` (+1 байт фільтра) починаючи з raw[pos:]; повертає (список рядків bytearray, нова позиція)."""
    out = []
    prev = bytearray(rowbytes)
    for _ in range(rows):
        if pos + 1 + rowbytes > len(raw):
            raise ImageError("PNG обірваний: даних менше, ніж треба для зображення")
        ft = raw[pos]
        cur = bytearray(raw[pos + 1:pos + 1 + rowbytes])
        pos += 1 + rowbytes
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(bpp, rowbytes):
                cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif ft == 2:
            for i in range(rowbytes):
                cur[i] = (cur[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(rowbytes):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(rowbytes):
                left = cur[i - bpp] if i >= bpp else 0
                ul = prev[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + _paeth(left, prev[i], ul)) & 255
        else:
            raise ImageError("PNG: невідомий фільтр рядка %d" % ft)
        out.append(cur)
        prev = cur
    return out, pos


def _row_gray(row, npix, ct, depth, pal, trns, bg):
    """Один рядок PNG (після зняття фільтрів) -> список яскравостей 0..255."""
    out = [0] * npix
    if ct == 0:                       # сірий
        if depth == 16:
            tr = trns
            for i in range(npix):
                v = (row[2 * i] << 8) | row[2 * i + 1]
                g = row[2 * i]
                out[i] = bg if (tr is not None and v == tr) else g
        elif depth == 8:
            for i in range(npix):
                v = row[i]
                out[i] = bg if (trns is not None and v == trns) else v
        else:
            mask = (1 << depth) - 1
            scale = 255 // mask
            per = 8 // depth
            for i in range(npix):
                byte = row[i // per]
                shift = 8 - depth * (i % per + 1)
                v = (byte >> shift) & mask
                out[i] = bg if (trns is not None and v == trns) else v * scale
    elif ct == 2:                     # RGB
        if depth == 8:
            for i in range(npix):
                r, g, b = row[3 * i], row[3 * i + 1], row[3 * i + 2]
                if trns is not None and (r, g, b) == trns:
                    out[i] = bg
                else:
                    out[i] = _lum(r, g, b)
        else:
            for i in range(npix):
                r16 = (row[6 * i] << 8) | row[6 * i + 1]
                g16 = (row[6 * i + 2] << 8) | row[6 * i + 3]
                b16 = (row[6 * i + 4] << 8) | row[6 * i + 5]
                if trns is not None and (r16, g16, b16) == trns:
                    out[i] = bg
                else:
                    out[i] = _lum(row[6 * i], row[6 * i + 2], row[6 * i + 4])
    elif ct == 3:                     # палітра
        per = 8 // depth
        mask = (1 << depth) - 1
        for i in range(npix):
            byte = row[i // per] if depth < 8 else row[i]
            idx = byte if depth == 8 else (byte >> (8 - depth * (i % per + 1))) & mask
            if idx >= len(pal):
                raise ImageError("PNG: індекс кольору %d поза палітрою" % idx)
            r, g, b, a = pal[idx]
            out[i] = _over(_lum(r, g, b), a, bg)
    elif ct == 4:                     # сірий + альфа
        step = 2 if depth == 8 else 4
        for i in range(npix):
            out[i] = _over(row[step * i], row[step * i + (1 if depth == 8 else 2)], bg)
    elif ct == 6:                     # RGBA
        step = 4 if depth == 8 else 8
        ao = 3 if depth == 8 else 6
        co = 1 if depth == 8 else 2
        for i in range(npix):
            b0 = step * i
            out[i] = _over(_lum(row[b0], row[b0 + co], row[b0 + 2 * co]), row[b0 + ao], bg)
    return out


def decode_png(data, transparent_to=255):
    pos = 8
    ihdr = None
    pal = []
    plte = None
    trns_raw = None
    idat = bytearray()
    while pos + 8 <= len(data):
        ln, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        if len(body) != ln:
            raise ImageError("PNG обірваний у чанку %s" % tag.decode("latin-1"))
        pos += 12 + ln
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns_raw = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if ihdr is None:
        raise ImageError("PNG без заголовка IHDR")
    w, h, depth, ct, comp, filt, inter = ihdr
    if w <= 0 or h <= 0:
        raise ImageError("PNG з нульовим розміром")
    if w * h > MAX_PIXELS:
        raise ImageError("картинка завелика (%d x %d); зменшіть її до ~%d млн точок" % (w, h, MAX_PIXELS // 1000000))
    if comp != 0 or filt != 0 or inter not in (0, 1):
        raise ImageError("PNG з невідомим методом стиснення/фільтрації/переплетення")
    ok = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if ct not in ok or depth not in ok[ct]:
        raise ImageError("PNG: недопустима комбінація типу кольору %d і глибини %d" % (ct, depth))
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    bpp_bits = chans * depth
    bpp = max(1, bpp_bits // 8)
    trns = None
    if ct == 3:
        if plte is None:
            raise ImageError("PNG з палітрою без чанка PLTE")
        pal = [(plte[3 * i], plte[3 * i + 1], plte[3 * i + 2], 255) for i in range(len(plte) // 3)]
        if trns_raw:
            for i, a in enumerate(trns_raw[:len(pal)]):
                r, g, b, _a = pal[i]
                pal[i] = (r, g, b, a)
    elif trns_raw:
        if ct == 0 and len(trns_raw) >= 2:
            trns = struct.unpack(">H", trns_raw[:2])[0]
            if depth < 16:
                trns &= (1 << depth) - 1
        elif ct == 2 and len(trns_raw) >= 6:
            r, g, b = struct.unpack(">HHH", trns_raw[:6])
            trns = (r, g, b) if depth == 16 else (r & 255, g & 255, b & 255)
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise ImageError("PNG: дані пошкоджено (%s)" % e)
    gray = bytearray(w * h)
    bg = transparent_to
    if inter == 0:
        rowbytes = (w * bpp_bits + 7) // 8
        rows, _p = _unfilter(raw, 0, h, rowbytes, bpp)
        for y, row in enumerate(rows):
            gray[y * w:(y + 1) * w] = bytes(_row_gray(row, w, ct, depth, pal, trns, bg))
    else:
        passes = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
        pos2 = 0
        for (x0, y0, dx, dy) in passes:
            pw = (w - x0 + dx - 1) // dx if w > x0 else 0
            ph = (h - y0 + dy - 1) // dy if h > y0 else 0
            if pw == 0 or ph == 0:
                continue
            rowbytes = (pw * bpp_bits + 7) // 8
            rows, pos2 = _unfilter(raw, pos2, ph, rowbytes, bpp)
            for j, row in enumerate(rows):
                vals = _row_gray(row, pw, ct, depth, pal, trns, bg)
                y = y0 + j * dy
                for i, v in enumerate(vals):
                    gray[y * w + x0 + i * dx] = v
    return Gray(w, h, bytes(gray))


def decode_bmp(data, transparent_to=255):
    if len(data) < 54:
        raise ImageError("BMP занадто короткий")
    off = struct.unpack("<I", data[10:14])[0]
    hsize = struct.unpack("<I", data[14:18])[0]
    if hsize < 40:
        raise ImageError("BMP старого формату (заголовок %d Б) не підтримується" % hsize)
    w, h, planes, bits, comp = struct.unpack("<iiHHI", data[18:34])
    ncol = struct.unpack("<I", data[46:50])[0]
    if comp not in (0, 3) or (comp == 3 and bits not in (16, 32)):
        raise ImageError("BMP зі стисненням (%d) не підтримується -- збережіть без стиснення" % comp)
    if comp == 3 and bits == 16:
        raise ImageError("BMP 16 біт не підтримується")
    top_down = h < 0
    h = abs(h)
    if w <= 0 or h == 0 or w * h > MAX_PIXELS:
        raise ImageError("BMP: некоректний або завеликий розмір %d x %d" % (w, h))
    pal = []
    if bits <= 8:
        n = ncol or (1 << bits)
        p0 = 14 + hsize
        for i in range(n):
            b, g, r = data[p0 + 4 * i], data[p0 + 4 * i + 1], data[p0 + 4 * i + 2]
            pal.append(_lum(r, g, b))
    elif bits not in (24, 32):
        raise ImageError("BMP з %d бітами на точку не підтримується" % bits)
    rowbytes = ((w * bits + 31) // 32) * 4
    if off + rowbytes * h > len(data):
        raise ImageError("BMP обірваний")
    gray = bytearray(w * h)
    for j in range(h):
        y = j if top_down else h - 1 - j
        row = data[off + j * rowbytes: off + (j + 1) * rowbytes]
        for x in range(w):
            if bits == 24:
                v = _lum(row[3 * x + 2], row[3 * x + 1], row[3 * x])
            elif bits == 32:
                a = row[4 * x + 3]
                v = _over(_lum(row[4 * x + 2], row[4 * x + 1], row[4 * x]), a if a else 255, transparent_to)     # a == 0 у BMP 32 -- звично «альфи нема»
            elif bits == 8:
                v = pal[row[x]] if row[x] < len(pal) else 0
            else:
                per = 8 // bits
                idx = (row[x // per] >> (8 - bits * (x % per + 1))) & ((1 << bits) - 1)
                v = pal[idx] if idx < len(pal) else 0
            gray[y * w + x] = v
    return Gray(w, h, bytes(gray))


def decode_pnm(data):
    """P1/P4 (біти), P2/P5 (сірий), P3/P6 (колір). Максимальне значення > 255 зводиться до 8 біт."""
    kind = data[1:2]
    pos = 2
    toks = []

    def token():
        nonlocal pos
        while pos < len(data):
            c = data[pos:pos + 1]
            if c == b"#":
                while pos < len(data) and data[pos:pos + 1] != b"\n":
                    pos += 1
            elif c in b" \t\r\n":
                pos += 1
            else:
                break
        s = pos
        while pos < len(data) and data[pos:pos + 1] not in b" \t\r\n":
            pos += 1
        return data[s:pos]
    try:
        w, h = int(token()), int(token())
        mx = 1 if kind in b"14" else int(token())
    except ValueError:
        raise ImageError("PNM: заголовок пошкоджено")
    if w <= 0 or h <= 0 or w * h > MAX_PIXELS or mx <= 0 or mx > 65535:
        raise ImageError("PNM: некоректні розміри")
    gray = bytearray(w * h)
    if kind in b"456":
        pos += 1                         # один пробільний символ після заголовка
        if kind == b"4":
            rb = (w + 7) // 8
            for y in range(h):
                row = data[pos + y * rb: pos + (y + 1) * rb]
                if len(row) < rb:
                    raise ImageError("PNM обірваний")
                for x in range(w):
                    gray[y * w + x] = 0 if (row[x // 8] >> (7 - x % 8)) & 1 else 255
        else:
            chans = 1 if kind == b"5" else 3
            bw = 2 if mx > 255 else 1
            need = w * h * chans * bw
            body = data[pos:pos + need]
            if len(body) < need:
                raise ImageError("PNM обірваний")
            for i in range(w * h):
                vals = []
                for c in range(chans):
                    o = (i * chans + c) * bw
                    v = body[o] if bw == 1 else ((body[o] << 8) | body[o + 1])
                    vals.append(v * 255 // mx)
                gray[i] = vals[0] if chans == 1 else _lum(*vals)
    else:
        chans = 3 if kind == b"3" else 1
        for i in range(w * h):
            if kind == b"1":
                t = token()
                if t not in (b"0", b"1"):
                    raise ImageError("PNM обірваний")
                gray[i] = 0 if t == b"1" else 255
            else:
                vals = []
                for _ in range(chans):
                    t = token()
                    if not t:
                        raise ImageError("PNM обірваний")
                    vals.append(int(t) * 255 // mx)
                gray[i] = vals[0] if chans == 1 else _lum(*vals)
    return Gray(w, h, bytes(gray))


# ---------------------------------------------------------------------------------------------------------------------------------
#  Запис PNG (для «Зберегти у PNG» і тестів)
# ---------------------------------------------------------------------------------------------------------------------------------

def _chunk(tag, body):
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def encode_png_rgb(w, h, rgb):
    """rgb: bytes довжиною w*h*3 -> PNG (8 біт, без переплетення, фільтр 0)."""
    if len(rgb) != w * h * 3:
        raise ImageError("внутрішня помилка: розмір RGB")
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def encode_png_gray(w, h, gray):
    if len(gray) != w * h:
        raise ImageError("внутрішня помилка: розмір сірого")
    raw = b"".join(b"\x00" + bytes(gray[y * w:(y + 1) * w]) for y in range(h))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


# ---------------------------------------------------------------------------------------------------------------------------------
#  Масштабування
# ---------------------------------------------------------------------------------------------------------------------------------

def _axis_weights(src, dst, start=0.0, span=None):
    """Для кожної цільової точки -- список (індекс вихідної, вага) за точною площею перекриття. Діапазон вихідної осі [start, start+span)."""
    span = float(src if span is None else span)
    step = span / dst
    out = []
    for d in range(dst):
        a = start + d * step
        b = a + step
        i0 = int(a)
        i1 = min(src - 1, int(b - 1e-9))
        ws = []
        for i in range(max(0, i0), i1 + 1):
            lo, hi = max(a, i), min(b, i + 1)
            if hi > lo:
                ws.append((i, hi - lo))
        tot = sum(w for _i, w in ws) or 1.0
        out.append([(i, w / tot) for i, w in ws])
    return out


def resample(g, dw, dh, crop=None):
    """Усереднення за площею. crop = (x, y, w, h) у координатах джерела (дробові) -- вирізати перед зменшенням. Повертає bytes dw*dh."""
    cx, cy, cw, ch = crop if crop else (0.0, 0.0, float(g.w), float(g.h))
    wx = _axis_weights(g.w, dw, cx, cw)
    wy = _axis_weights(g.h, dh, cy, ch)
    src = g.data
    w = g.w
    # горизонтальний прохід лише для потрібних рядків
    needed = sorted({i for col in wy for i, _ in col})
    tmp = {}
    for y in needed:
        row = src[y * w:(y + 1) * w]
        tmp[y] = [sum(row[i] * k for i, k in col) for col in wx]
    out = bytearray(dw * dh)
    for dy, col in enumerate(wy):
        for dx in range(dw):
            v = sum(tmp[i][dx] * k for i, k in col)
            out[dy * dw + dx] = max(0, min(255, int(v + 0.5)))
    return bytes(out)


def fit_to_area(g, mode="fit", tw=W, th=H):
    """Вмістити картинку в область tw x th. Повертає (gray bytes tw*th, covered bytes tw*th) -- covered[i] = 1, якщо точка належить картинці
    (поля режиму «вписати» -- 0, вони стануть тлом заставки)."""
    if mode == "stretch":
        return resample(g, tw, th), bytes([1]) * (tw * th)
    if mode == "fill":
        sc = max(tw / g.w, th / g.h)
        cw, ch = tw / sc, th / sc
        cx, cy = (g.w - cw) / 2.0, (g.h - ch) / 2.0
        return resample(g, tw, th, (cx, cy, cw, ch)), bytes([1]) * (tw * th)
    if mode == "fit":
        sc = min(tw / g.w, th / g.h)
        nw, nh = max(1, int(round(g.w * sc))), max(1, int(round(g.h * sc)))
        nw, nh = min(nw, tw), min(nh, th)
        small = resample(g, nw, nh)
        ox, oy = (tw - nw) // 2, (th - nh) // 2
        gray = bytearray(tw * th)
        cov = bytearray(tw * th)
        for y in range(nh):
            gray[(oy + y) * tw + ox:(oy + y) * tw + ox + nw] = small[y * nw:(y + 1) * nw]
            cov[(oy + y) * tw + ox:(oy + y) * tw + ox + nw] = b"\x01" * nw
        return bytes(gray), bytes(cov)
    raise ImageError("невідомий спосіб вписування «%s»" % mode)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Квантування до 1 біта
# ---------------------------------------------------------------------------------------------------------------------------------

BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def quantize(gray, covered=None, w=W, h=H, mode="threshold", threshold=128, bright_is_ink=True):
    """gray (w*h, 0..255) -> ink: bytes w*h, 1 = точка кольору ПЕРЕДНЬОГО плану, 0 = тла. covered[i] == 0 -- завжди тло.
    bright_is_ink: True -- світлі точки джерела стають кольором переднього плану (нічна тема: світле на темному); False -- навпаки."""
    covered = covered if covered is not None else bytes([1]) * (w * h)
    val = [float(v) if bright_is_ink else 255.0 - v for v in gray]
    thr = float(threshold if bright_is_ink else 255 - threshold)
    ink = bytearray(w * h)
    if mode == "threshold":
        for i, v in enumerate(val):
            ink[i] = 1 if (covered[i] and v >= thr) else 0
    elif mode == "bayer":
        for y in range(h):
            for x in range(w):
                i = y * w + x
                t = thr + (BAYER4[y & 3][x & 3] - 7.5) * (255.0 / 16.0)
                ink[i] = 1 if (covered[i] and val[i] >= t) else 0
    elif mode == "dither":
        buf = [v - (thr - 128.0) for v in val]                  # поріг зсуває яскравість, як у режимі порога
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if not covered[i]:
                    continue
                old = buf[i]
                new = 255.0 if old >= 128.0 else 0.0
                ink[i] = 1 if new else 0
                err = old - new
                if x + 1 < w and covered[i + 1]:
                    buf[i + 1] += err * 7 / 16
                if y + 1 < h:
                    if x > 0 and covered[i + w - 1]:
                        buf[i + w - 1] += err * 3 / 16
                    if covered[i + w]:
                        buf[i + w] += err * 5 / 16
                    if x + 1 < w and covered[i + w + 1]:
                        buf[i + w + 1] += err * 1 / 16
    else:
        raise ImageError("невідомий спосіб квантування «%s»" % mode)
    return bytes(ink)


def convert(g, fit="fit", quant="threshold", threshold=128, bright_is_ink=True):
    """Gray -> ink 128x64 (bytes, 1 = колір переднього плану)."""
    gray, cov = fit_to_area(g, fit)
    return quantize(gray, cov, W, H, quant, threshold, bright_is_ink)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Блок
# ---------------------------------------------------------------------------------------------------------------------------------

def ink_to_block(ink):
    """ink 128x64 (1 = передній план) -> 1024 байти блока. Біт 1 = тло, біт 0 = передній план."""
    if len(ink) != W * H:
        raise ImageError("очікувалось %d точок, є %d" % (W * H, len(ink)))
    out = bytearray(BLOCK_LEN)
    for page in range(H // 8):
        for x in range(W):
            d = 0
            for r in range(8):
                if not ink[(page * 8 + r) * W + x]:
                    d |= 1 << r
            out[page * W + x] = d
    return bytes(out)


def block_to_ink(block):
    """1024 байти (або більше -- решта ігнорується, як у прошивці) -> ink 128x64."""
    block = bytes(block)
    if len(block) < BLOCK_LEN:
        raise ImageError("блок картинки коротший за %d байтів (є %d)" % (BLOCK_LEN, len(block)))
    ink = bytearray(W * H)
    for page in range(H // 8):
        for x in range(W):
            d = block[page * W + x]
            for r in range(8):
                if not (d >> r) & 1:
                    ink[(page * 8 + r) * W + x] = 1
    return bytes(ink)


def ink_to_gray_png(ink, scale=1, ink_value=255):
    """Чорно-біла PNG 128x64 (за замовчуванням: передній план білий на чорному -- так само, як читає її імпорт за замовчуванням)."""
    bg = 0 if ink_value == 255 else 255
    rows = []
    for y in range(H):
        row = bytearray()
        for x in range(W):
            v = ink_value if ink[y * W + x] else bg
            row += bytes([v]) * scale
        rows += [bytes(row)] * scale
    return encode_png_gray(W * scale, H * scale, b"".join(rows))


def screen_rgb(ink, fg_rgb, bg_rgb):
    """Екран 160x128, як на рації: картинка в (16, 32), решта -- колір тла. Повертає bytes RGB."""
    out = bytearray()
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            cx, cy = x - OFFSET_X, y - OFFSET_Y
            if 0 <= cx < W and 0 <= cy < H and ink[cy * W + cx]:
                out += bytes(fg_rgb)
            else:
                out += bytes(bg_rgb)
    return bytes(out)


def screen_png(ink, fg_rgb, bg_rgb, scale=1):
    rgb = screen_rgb(ink, fg_rgb, bg_rgb)
    if scale > 1:
        rows = []
        for y in range(SCREEN_H):
            row = rgb[y * SCREEN_W * 3:(y + 1) * SCREEN_W * 3]
            big = b"".join(row[3 * x:3 * x + 3] * scale for x in range(SCREEN_W))
            rows += [big] * scale
        return encode_png_rgb(SCREEN_W * scale, SCREEN_H * scale, b"".join(rows))
    return encode_png_rgb(SCREEN_W, SCREEN_H, rgb)


def splash_display(ink, fg_item, bg_item):
    """Екран заставки з картинкою рендером «Тем» (screen_sim): та сама послідовність, що в updateScreen() -- тема FG/BG заставки, очищення тлом, картинка."""
    import screen_sim as sim
    d = sim.Display()
    d.theme_reset()
    d.theme_apply(fg_item, bg_item)
    d.clear_buf()
    for y in range(H):
        for x in range(W):
            d._put(OFFSET_X + x, OFFSET_Y + y, fg_item if ink[y * W + x] else bg_item)
    d.theme_reset()
    return d


# ---------------------------------------------------------------------------------------------------------------------------------
#  Рація
# ---------------------------------------------------------------------------------------------------------------------------------

ST_OK, ST_ABSENT, ST_NOREGION, ST_BADLEN = "ok", "absent", "noregion", "badlen"
STATE_TEXT = {
    ST_OK: "картинка є в рації",
    ST_ABSENT: "картинки в рації нема (показується текстова заставка)",
    ST_NOREGION: "область custom-data у рації не знайдено (немає заголовка OpenGD77) -- записати не можна",
    ST_BADLEN: "блок картинки в рації має довжину не 1024 Б -- прошивка не дозволяє міняти довжину блока, записати не можна (її можна лише вилучити й додати знову)",
}


def read_image(ser):
    """-> (стан, ink|None, довжина блока|None)."""
    import custom_data as cd
    kind, addr, ln = cd.find_or_alloc_block(ser, BLOCK_TYPE, 0)
    if kind is None:
        return ST_NOREGION, None, None
    if kind == "empty":
        return ST_ABSENT, None, None
    raw = cd._read_region(ser, addr + cd.HDR_LEN, min(ln, BLOCK_LEN))
    ink = block_to_ink(raw) if ln >= BLOCK_LEN else None
    return (ST_OK if ln == BLOCK_LEN else ST_BADLEN), ink, ln


def write_image(ser, ink):
    """Записати картинку й перечитати для звірки. RuntimeError -- відмова, збій або НЕЗБІГ. Повертає текст."""
    import custom_data as cd
    payload = ink_to_block(ink)
    state, _ink, _ln = read_image(ser)
    if state in (ST_NOREGION, ST_BADLEN):
        raise RuntimeError("картинка не записана: " + STATE_TEXT[state])
    ok, msg = cd.write_block(ser, BLOCK_TYPE, payload)
    if not ok:
        raise RuntimeError("картинка не записана: " + msg)
    back = cd.read_block(ser, BLOCK_TYPE, BLOCK_LEN)
    if back != payload:
        raise RuntimeError("картинка записана, але звірка читанням НЕ збіглася -- повторіть запис")
    return "Картинка заставки записана (%s). Звірка читанням: OK." % msg


def remove_image(ser):
    """«Прибрати картинку»: вилучити блок (див. custom_data.retire_block). Текстова заставка повертається сама: прошивка малює текст, коли блока IMAGE нема."""
    import custom_data as cd
    ok, msg = cd.retire_block(ser, BLOCK_TYPE)
    if not ok:
        raise RuntimeError("картинку не вилучено: " + msg)
    return "Картинку вилучено (%s). Рація знову малюватиме текстову заставку." % msg
