# -*- coding: utf-8 -*-
"""screen_sim.py -- R33 R2: ТОЧНИЙ (піксель-у-піксель) рендер екрана рації для передпоказу тем у CPS. Без Tk: чиста логіка, тестується без вікна.

ЩО ЦЕ. Той самий дисплейний рівень, що в прошивці (application/source/hardware/HX8353E_display.c), переписаний 1:1 на Python: буфер 160x128, шрифти з
HX8353E_charset_UA.h (через font_data.py, його генерує font_gen.py), ті самі примітиви (текст без заливки тла, displayFillRect, displayDrawRect, лінії,
кола, закруглені прямокутники), та сама семантика прапорця isInverted (у кожного примітива вона своя -- див. коментарі біля методів) і ті самі
displayThemeApply / displayThemeResetToDefault. Екрани (screen_views.py) викликають їх у тому самому порядку з тими самими координатами, що й код
прошивки. Гліфи, лінії й заливки малюються тими самими формулами, тож піксель на цьому екрані там, де й піксель на рації.

ВІДМІННІСТЬ ВІД ЗРАЗКА З R28. Буфер тут зберігає НЕ колір, а ІНДЕКС ЕЛЕМЕНТА ТЕМИ (0..31, порядок themeItem_t = theme_edit.ITEMS). Колір береться
під час виводу в картинку (render_rgb). Тому: (1) зміна кольору однієї позиції не потребує перемальовування екрана; (2) клацання по пікселю точно
каже, який елемент теми його фарбує (hit_item) -- без жодних «тегів», розставлених руками.

МЕЖІ. Це знімок ОДНОГО стану екрана з прикладними даними (позивний, рівень сигналу, номери супутників -- вигадані, позначені як приклад). Те, що залежить
від стану рації й не моделюється, перелічено в screen_views.NOT_MODELLED і в TESTING.md (блок CJ).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import font_data as _fd          # noqa: E402
import theme_edit as te          # noqa: E402

W, H = 160, 128                 # DISPLAY_SIZE_X, DISPLAY_SIZE_Y (HX8353E.h)
NONE = -1                       # THEME_ITEM_COLOUR_NONE: «колір не міняти» (>= THEME_ITEM_MAX у прошивці)

FONT_1, FONT_1_BOLD, FONT_2, FONT_3, FONT_4 = 1, 2, 3, 4, 5      # ucFont_t: FONT_SIZE_1, _1_BOLD, _2, _3, _4
FONT_HEIGHT = {FONT_1: 8, FONT_1_BOLD: 8, FONT_2: 8, FONT_3: 16, FONT_4: 32}      # FONT_SIZE_n_HEIGHT (HX8353E.h)
_FONT_TABLE = {FONT_1: _fd.FONT_6X8, FONT_1_BOLD: _fd.FONT_6X8_BOLD, FONT_2: _fd.FONT_8X8, FONT_3: _fd.FONT_8X16, FONT_4: _fd.FONT_16X32_COMPRESSED}

ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT = 0, 1, 2

# Індекси елементів теми за ключем (без префікса THEME_ITEM_).
IT = dict(te.INDEX)


def _cdiv(a, b):
    """Ділення цілих як у C (до нуля), а не як у Python (до мінус нескінченності)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


class Font:
    """Шрифт прошивки: шапка з 8 байтів [прапорці, 0, перший_код, останній_код, ширина, висота, рядків_байтів, байтів_на_символ] і гліфи.
    Піксель (x, y) символа: байт `x + (y // 8) * ширина`, біт `y % 8` (displayPrintCoreDoubleHeight). Стиснений шрифт (прапорець 0x01) --
    RLE8: перед символом байт n, далі n пар (значення, довжина-1) (getUncompressedChar)."""

    def __init__(self, data):
        self.data = data
        self.compressed = bool(data[0] & 1)
        self.first, self.last, self.w, self.h, self.bpc = data[2], data[3], data[4], data[5], data[7]
        self._cache = {}
        self._index = None
        if self.compressed:
            self._index = []
            pos = 8
            for _c in range(self.first, self.last + 1):
                n = data[pos]
                self._index.append(pos)
                pos += 1 + 2 * n

    def glyph(self, offset):
        """Байти гліфа для зсуву `offset` (код - перший_код); None, якщо поза таблицею."""
        g = self._cache.get(offset)
        if g is not None:
            return g
        if offset < 0 or offset > self.last - self.first:
            return None
        if self.compressed:
            pos = self._index[offset]
            n = self.data[pos]
            out = bytearray()
            for i in range(n):
                val, ln = self.data[pos + 1 + 2 * i], self.data[pos + 2 + 2 * i]
                out += bytes([val]) * (ln + 1)
            g = bytes(out)
        else:
            g = self.data[8 + offset * self.bpc: 8 + (offset + 1) * self.bpc]
        self._cache[offset] = g
        return g


FONTS = {k: Font(v) for k, v in _FONT_TABLE.items()}


def to_bytes(text):
    """Рядок -> байти cp1251, як у мовних файлах (languages/ukrainian.h -- cp1251). Символ поза cp1251 -> '?'."""
    return text.encode("cp1251", errors="replace")


class Display:
    """Буфер екрана 160x128 з індексами елементів теми + стан displayThemeApply. Усі методи названі як у прошивці (без префікса display)."""

    def __init__(self):
        self.px = bytearray(W * H)
        self.fg = IT["FG_DEFAULT"]
        self.bg = IT["BG"]
        self.clear_buf()

    # --- тема --------------------------------------------------------------------------------------------------------------------------
    def theme_apply(self, fg, bg=NONE):
        """displayThemeApply: елемент < THEME_ITEM_MAX змінює, NONE -- лишає як було."""
        if fg != NONE:
            self.fg = fg
        if bg != NONE:
            self.bg = bg

    def theme_reset(self):
        """displayThemeResetToDefault."""
        self.fg = IT["FG_DEFAULT"]
        self.bg = IT["BG"]

    def theme_fg_is(self, item):
        """displayThemeIsForegroundColourEqualTo (порівнюється ЕЛЕМЕНТ, а не колір)."""
        return self.fg == item

    def theme_get(self):
        return self.fg, self.bg

    # --- буфер -------------------------------------------------------------------------------------------------------------------------
    def clear_buf(self):
        """displayClearBuf: заливає ПОТОЧНИМ кольором тла."""
        self.px[:] = bytes([self.bg]) * (W * H)

    def clear_rows(self, start_row, end_row, inverted):
        """displayClearRows: рядки по 8 пікселів; inverted -> кольором переднього плану."""
        if start_row < 0 or end_row < 0 or start_row > H // 8 or end_row > H // 8 or start_row == end_row:
            return
        if end_row < start_row:
            start_row, end_row = end_row, start_row
        v = self.fg if inverted else self.bg
        self.px[start_row * 8 * W: end_row * 8 * W] = bytes([v]) * ((end_row - start_row) * 8 * W)

    def _put(self, x, y, item):
        if 0 <= x < W and 0 <= y < H:
            self.px[y * W + x] = item

    def set_pixel(self, x, y, inverted):
        """displaySetPixel: inverted=true -> ПЕРЕДНІЙ план (тут навпаки, ніж у displayFillRect)."""
        self._put(x, y, self.fg if inverted else self.bg)

    # --- текст -------------------------------------------------------------------------------------------------------------------------
    def print_core(self, x, y, text, font, align=ALIGN_LEFT, inverted=False, double_height=False):
        """displayPrintCoreDoubleHeight. Малюються ТІЛЬКИ пікселі гліфа (тло символа не заливається); пробіл пропускається; рядок обрізається по
        правому краю ДО вирівнювання (як у прошивці); код нижче першого коду шрифту -> '?'."""
        f = FONTS[font]
        msg = to_bytes(text) if isinstance(text, str) else bytes(text)
        n = len(msg)
        if f.w * n + x > W:
            n = (W - x) // f.w
        if n < 0:
            return -1
        if align == ALIGN_CENTER:
            x = (W - f.w * n) >> 1
        elif align == ALIGN_RIGHT:
            x = W - f.w * n
        item = self.bg if inverted else self.fg
        for i in range(n):
            ch = msg[i]
            if ch == 0x20:
                continue
            off = ch - f.first
            if off < 0 or off > f.last:                  # uint32 у прошивці: код < перший_код дає величезне число -> '?'
                off = ord("?") - f.first
            g = f.glyph(off)
            if g is None:
                continue
            base = i * f.w
            for gx in range(f.w):
                for gy in range(f.h):
                    if (g[gx + (gy // 8) * f.w] >> (gy % 8)) & 1:
                        px = x + base + gx
                        py = y + gy * (2 if double_height else 1)
                        self._put(px, py, item)
                        if double_height:
                            self._put(px, py + 1, item)
        return 0

    def print_centered(self, y, text, font, double_height=False):
        return self.print_core(0, y, text, font, ALIGN_CENTER, False, double_height)

    def print_at(self, x, y, text, font, double_height=False):
        return self.print_core(x, y, text, font, ALIGN_LEFT, False, double_height)

    # --- прямокутники й лінії ----------------------------------------------------------------------------------------------------------
    def fill_rect(self, x, y, w, h, inverted):
        """displayFillRect: inverted=true -> колір ТЛА, false -> колір ПЕРЕДНЬОГО плану."""
        v = self.bg if inverted else self.fg
        for yy in range(y, y + h):
            if 0 <= yy < H:
                x0, x1 = max(0, x), min(W, x + w)
                if x1 > x0:
                    self.px[yy * W + x0: yy * W + x1] = bytes([v]) * (x1 - x0)

    def fast_hline(self, x, y, w, inverted):
        """displayDrawFastHLine: усередині fill_rect з !inverted, тож inverted=true -> ПЕРЕДНІЙ план."""
        self.fill_rect(x, y, w, 1, not inverted)

    def fast_vline(self, x, y, h, inverted):
        self.fill_rect(x, y, 1, h, not inverted)

    def draw_rect(self, x, y, w, h, inverted):
        """displayDrawRect (чотири fast-лінії): inverted=true -> рамка ПЕРЕДНІМ планом."""
        self.fast_hline(x, y, w, inverted)
        self.fast_hline(x, y + h - 1, w, inverted)
        self.fast_vline(x, y, h, inverted)
        self.fast_vline(x + w - 1, y, h, inverted)

    def draw_line(self, x0, y0, x1, y1, inverted):
        """displayDrawLine (Брезенхем з прошивки)."""
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0 = y0, x0
            x1, y1 = y1, x1
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        dx = x1 - x0
        dy = abs(y1 - y0)
        err = dx >> 1
        ystep = 1 if y0 < y1 else -1
        while x0 <= x1:
            if steep:
                self.set_pixel(y0, x0, inverted)
            else:
                self.set_pixel(x0, y0, inverted)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1

    # --- кола й закруглені прямокутники ------------------------------------------------------------------------------------------------
    def draw_circle(self, x0, y0, r, inverted):
        """displayDrawCircle."""
        f, ddf_x, ddf_y, x, y = 1 - r, 1, -2 * r, 0, r
        for dx, dy in ((0, r), (0, -r), (r, 0), (-r, 0)):
            self.set_pixel(x0 + dx, y0 + dy, inverted)
        while x < y:
            if f >= 0:
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            for sx, sy in ((x, y), (-x, y), (x, -y), (-x, -y), (y, x), (-y, x), (y, -x), (-y, -x)):
                self.set_pixel(x0 + sx, y0 + sy, inverted)

    def draw_circle_helper(self, x0, y0, r, corner, inverted):
        """displayDrawCircleHelper."""
        f, ddf_x, ddf_y, x, y = 1 - r, 1, -2 * r, 0, r
        while x < y:
            if f >= 0:
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            if corner & 0x4:
                self.set_pixel(x0 + x, y0 + y, inverted)
                self.set_pixel(x0 + y, y0 + x, inverted)
            if corner & 0x2:
                self.set_pixel(x0 + x, y0 - y, inverted)
                self.set_pixel(x0 + y, y0 - x, inverted)
            if corner & 0x8:
                self.set_pixel(x0 - y, y0 + x, inverted)
                self.set_pixel(x0 - x, y0 + y, inverted)
            if corner & 0x1:
                self.set_pixel(x0 - y, y0 - x, inverted)
                self.set_pixel(x0 - x, y0 - y, inverted)

    def fill_circle_helper(self, x0, y0, r, corner, delta, inverted):
        """displayFillCircleHelper."""
        f, ddf_x, ddf_y, x, y = 1 - r, 1, -2 * r, 0, r
        while x < y:
            if f >= 0:
                y -= 1
                ddf_y += 2
                f += ddf_y
            x += 1
            ddf_x += 2
            f += ddf_x
            if corner & 0x1:
                self.fast_vline(x0 + x, y0 - y, 2 * y + 1 + delta, inverted)
                self.fast_vline(x0 + y, y0 - x, 2 * x + 1 + delta, inverted)
            if corner & 0x2:
                self.fast_vline(x0 - x, y0 - y, 2 * y + 1 + delta, inverted)
                self.fast_vline(x0 - y, y0 - x, 2 * x + 1 + delta, inverted)

    def fill_circle(self, x0, y0, r, inverted):
        """displayFillCircle: inverted=true -> ПЕРЕДНІЙ план (через fast_vline)."""
        self.fast_vline(x0, y0 - r, 2 * r + 1, inverted)
        self.fill_circle_helper(x0, y0, r, 3, 0, inverted)

    def draw_round_rect(self, x, y, w, h, r, inverted):
        """displayDrawRoundRect: inverted=true -> ПЕРЕДНІЙ план."""
        self.fast_hline(x + r, y, w - 2 * r, inverted)
        self.fast_hline(x + r, y + h - 1, w - 2 * r, inverted)
        self.fast_vline(x, y + r, h - 2 * r, inverted)
        self.fast_vline(x + w - 1, y + r, h - 2 * r, inverted)
        self.draw_circle_helper(x + r, y + r, r, 1, inverted)
        self.draw_circle_helper(x + w - r - 1, y + r, r, 2, inverted)
        self.draw_circle_helper(x + w - r - 1, y + h - r - 1, r, 4, inverted)
        self.draw_circle_helper(x + r, y + h - r - 1, r, 8, inverted)

    def fill_round_rect(self, x, y, w, h, r, inverted):
        """displayFillRoundRect: тіло через fill_rect(!inverted), кути через fast_vline -- тож inverted=true -> ПЕРЕДНІЙ план (пастка API з коментаря
        в uiUtilities.c)."""
        self.fill_rect(x + r, y, w - 2 * r, h, not inverted)
        self.fill_circle_helper(x + w - r - 1, y + r, r, 1, h - 2 * r - 1, inverted)
        self.fill_circle_helper(x + r, y + r, r, 2, h - 2 * r - 1, inverted)

    def draw_round_rect_with_shadow(self, x, y, w, h, r, inverted):
        """displayDrawRoundRectWithDropShadow: тінь (передній план) зі зсувом +2 по x, порожня коробка тлом на 2 вище, контур переднім планом."""
        self.fill_round_rect(x + 2, y, w, h, r, inverted)
        self.fill_round_rect(x, y - 2, w, h, r, not inverted)
        self.draw_round_rect(x, y - 2, w, h, r, inverted)

    def draw_triangle(self, x0, y0, x1, y1, x2, y2, inverted):
        """displayDrawTriangle."""
        self.draw_line(x0, y0, x1, y1, inverted)
        self.draw_line(x1, y1, x2, y2, inverted)
        self.draw_line(x2, y2, x0, y0, inverted)

    def fill_triangle(self, x0, y0, x1, y1, x2, y2, inverted):
        """displayFillTriangle (Adafruit GFX у версії прошивки; ділення цілих -- як у C, до нуля). inverted=true -> ПЕРЕДНІЙ план (fast_hline)."""
        if y0 > y1:
            y0, y1, x0, x1 = y1, y0, x1, x0
        if y1 > y2:
            y2, y1, x2, x1 = y1, y2, x1, x2
        if y0 > y1:
            y0, y1, x0, x1 = y1, y0, x1, x0
        if y0 == y2:
            a = b = x0
            if x1 < a:
                a = x1
            elif x1 > b:
                b = x1
            if x2 < a:
                a = x2
            elif x2 > b:
                b = x2
            self.fast_hline(a, y0, b - a + 1, inverted)
            return
        dx01, dy01, dx02, dy02, dx12, dy12 = x1 - x0, y1 - y0, x2 - x0, y2 - y0, x2 - x1, y2 - y1
        sa = sb = 0
        last = y1 if y1 == y2 else y1 - 1
        y = y0
        while y <= last:
            a = x0 + _cdiv(sa, dy01)
            b = x0 + _cdiv(sb, dy02)
            sa += dx01
            sb += dx02
            if a > b:
                a, b = b, a
            self.fast_hline(a, y, b - a + 1, inverted)
            y += 1
        sa = dx12 * (y - y1)
        sb = dx02 * (y - y0)
        while y <= y2:
            a = x1 + _cdiv(sa, dy12)
            b = x0 + _cdiv(sb, dy02)
            sa += dx12
            sb += dx02
            if a > b:
                a, b = b, a
            self.fast_hline(a, y, b - a + 1, inverted)
            y += 1

    def draw_xbitmap(self, x, y, bitmap, w, h, inverted):
        """displayDrawXBitmap (формат XBM: молодший біт байта -- лівий піксель; рядок = ceil(w/8) байтів)."""
        bw = (w + 7) // 8
        for j in range(h):
            for i in range(w):
                if (bitmap[j * bw + i // 8] >> (i & 7)) & 1:
                    self.set_pixel(x + i, y + j, inverted)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Вивід у картинку
# ---------------------------------------------------------------------------------------------------------------------------------

def palette(colors):
    """32 значення RGB565 -> 32 рядки '#RRGGBB' (так само, як їх показує список кольорів)."""
    return [te.to_hex(c) for c in colors]


def render_rows(display, colors):
    """[рядок '{#rrggbb #rrggbb ...}', ...] для tk.PhotoImage.put -- по одному на рядок екрана."""
    pal = palette(colors)
    out = []
    px = display.px
    for y in range(H):
        row = px[y * W:(y + 1) * W]
        out.append("{" + " ".join(pal[i] for i in row) + "}")
    return out


def render_rgb(display, colors):
    """bytes RGB (W*H*3) -- для тестів і для збереження в PNG/PPM."""
    pal = []
    for c in colors:
        v = te.rgb565_to_888(c)
        pal.append(bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255)))
    return b"".join(pal[i] for i in display.px)


def pixel_item(display, x, y):
    """Індекс елемента теми, що фарбує піксель (x, y); None поза екраном."""
    if 0 <= x < W and 0 <= y < H:
        return display.px[y * W + x]
    return None


def hit_item(display, x, y):
    """Елемент для клацання: сам піксель, а якщо це загальне ТЛО -- то найчастіший інший елемент у сусідніх 8 пікселях (щоб тонкий текст
    можна було влучити; рамки по периметру тла від цього не страждають, бо там сусідами теж ТЛО)."""
    it = pixel_item(display, x, y)
    if it is None:
        return None
    if it != IT["BG"]:
        return it
    seen = {}
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            o = pixel_item(display, x + dx, y + dy)
            if o is not None and o != IT["BG"]:
                seen[o] = seen.get(o, 0) + 1
    if seen:
        return max(seen.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return it


def items_present(display):
    """Множина елементів теми, що реально з'явилися на екрані."""
    return set(display.px)


def write_ppm(path, display, colors, scale=1):
    """Зберегти екран у P6 PPM (без залежностей) -- для ручного порівняння зі знімком з рації."""
    rgb = render_rgb(display, colors)
    with open(path, "wb") as fh:
        fh.write(b"P6\n%d %d\n255\n" % (W * scale, H * scale))
        for y in range(H):
            row = b"".join(rgb[(y * W + x) * 3:(y * W + x) * 3 + 3] * scale for x in range(W))
            fh.write(row * scale)
