# -*- coding: utf-8 -*-
"""layout_probe.py -- R36 Z1: вимірювання, чи не обрізано текст у вікні CPS. Використовується тестом test_r36.py і для ручної діагностики
(`xvfb-run -a python3 tools/layout_probe.py` друкує звіт по всіх розділах на 1024x768 і 1920x1080).

Критерій «обрізано» вимірюється, а не оцінюється на око:
  1. підпис / кнопка / прапорець / перемикач, якому виділено менше місця, ніж він запитує (ширина або висота < запит);
  2. вміст Combobox / Spinbox (поточне значення), ширший за поле;
  3. віджет, що виступає за межі будь-якого предка, якщо в цьому напрямку предок не прокручується (прокрутку дає ScrollFrame, коли показано смугу);
  4. стовпці таблиць (FitTreeview): ширина менша за потрібну для заголовка й значень, і при цьому нема горизонтальної смуги;
  5. заголовки LabelFrame, ширші за рамку."""
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TEXT_CLASSES = ("TLabel", "Label", "TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton", "Radiobutton")
VALUE_CLASSES = ("TCombobox", "TSpinbox")
TOL = 1


def spin(app, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def _path(w):
    return str(w).replace(".!cpsapp", "")


def _scroll_host_of(canvas):
    """ScrollFrame, чиїм полотном є canvas (або None)."""
    p = canvas.master
    return p if hasattr(p, "h_scroll_active") and getattr(p, "canvas", None) is canvas else None


def _text_of(w):
    try:
        return str(w.cget("text"))
    except tk.TclError:
        return ""


def _font_of(w):
    try:
        name = str(w.cget("font"))
        return tkfont.nametofont(name) if name else tkfont.nametofont("TkDefaultFont")
    except tk.TclError:
        return tkfont.nametofont("TkDefaultFont")


def clipped_by_ancestors(w):
    """Список (напрямок, на скільки px) вихідного за межі предка, де прокрутка неможлива."""
    out = []
    if w.winfo_toplevel() is w:
        return out              # R50-fix: окреме вікно (діалог) не «виступає» з головного: це інше вікно ОС, його розмір задає менеджер вікон
    x0, y0 = w.winfo_rootx(), w.winfo_rooty()
    x1, y1 = x0 + w.winfo_width(), y0 + w.winfo_height()
    a = w.master
    while a is not None:
        try:
            ax0, ay0 = a.winfo_rootx(), a.winfo_rooty()
            ax1, ay1 = ax0 + a.winfo_width(), ay0 + a.winfo_height()
        except tk.TclError:
            break
        host = _scroll_host_of(a) if a.winfo_class() == "Canvas" else None
        h_ok = host.h_scroll_active() if host else False
        v_ok = host.v_scroll_active() if host else False
        if x1 > ax1 + TOL and not h_ok:
            out.append(("справа", x1 - ax1, _path(a)))
        if x0 < ax0 - TOL and not h_ok:
            out.append(("зліва", ax0 - x0, _path(a)))
        if y1 > ay1 + TOL and not v_ok:
            out.append(("знизу", y1 - ay1, _path(a)))
        if host:
            break               # полотно прокрутки -- межа видимості; усе вище лише містить саме полотно
        a = a.master if a.master is not None and a is not a.winfo_toplevel() else None
    return out


def probe_widget(w):
    """Список проблем одного віджета (порожній -- все гаразд)."""
    cls = w.winfo_class()
    issues = []
    if cls in TEXT_CLASSES:
        text = _text_of(w)
        if text.strip():
            if w.winfo_width() + TOL < w.winfo_reqwidth():
                issues.append("ширина %d < потрібної %d" % (w.winfo_width(), w.winfo_reqwidth()))
            if w.winfo_height() + TOL < w.winfo_reqheight():
                issues.append("висота %d < потрібної %d" % (w.winfo_height(), w.winfo_reqheight()))
    elif cls in VALUE_CLASSES:
        try:
            val = str(w.get())
        except tk.TclError:
            val = ""
        vals = [val]
        if cls == "TCombobox":
            try:
                vals += [str(v) for v in w.cget("values")]         # усі значення випадного списку, а не лише вибране: інакше довше значення обріжеться пізніше
            except tk.TclError:
                pass
        for v in vals:
            if not v:
                continue
            need = _font_of(w).measure(v) + 30
            if need > w.winfo_width() + TOL:
                issues.append("значення «%s» (%d px) не вміщується в поле шириною %d" % (v[:30], need, w.winfo_width()))
                break
    elif cls == "TLabelframe":
        text = _text_of(w)
        if text and _font_of(w).measure(text) + 24 > w.winfo_width() + TOL:
            issues.append("заголовок рамки «%s» ширший за рамку (%d)" % (text[:30], w.winfo_width()))
    elif cls == "Treeview" and hasattr(w, "clipped_columns"):
        bad = w.clipped_columns()
        host = w.master
        h_ok = hasattr(host, "h_scroll_visible") and host.h_scroll_visible()
        if bad and not h_ok:
            issues.append("стовпці %s вужчі за потрібне і нема горизонтальної смуги" % ", ".join(bad))
        if not bad:
            tot = w.total_width()
            if tot > w.winfo_width() + 3 and not h_ok:
                issues.append("стовпці разом (%d) ширші за таблицю (%d) без горизонтальної смуги" % (tot, w.winfo_width()))
    for d, n, a in clipped_by_ancestors(w):
        if w.winfo_class() in ("TFrame", "Frame", "Canvas", "TPanedwindow", "Panedwindow"):
            continue            # рамки-контейнери: їх вихід за межі видно через вміст
        issues.append("виступає %s на %d px за межі %s" % (d, n, a))
    return issues


def walk_viewable(root):
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            if not w.winfo_viewable():
                continue
        except tk.TclError:
            continue
        yield w
        stack.extend(w.winfo_children())


def probe_panel(app, key):
    """[(шлях, клас, текст, [проблеми])] для видимого вмісту розділу key."""
    host = app._hosts[key]
    out = []
    for w in walk_viewable(host):
        if getattr(w, "_data_colour", False):
            continue
        iss = probe_widget(w)
        if iss:
            out.append((_path(w), w.winfo_class(), _text_of(w)[:40], iss))
    return out


def run_all(app, sizes=((1024, 768), (1920, 1080)), keys=None, doc_states=(None,)):
    """{(розмір, стан документа, розділ): [проблеми]}; порожні розділи не потрапляють у результат."""
    result = {}
    keys = keys or [k for k in app.section_keys() if not k.startswith("grp_")]
    for (W, H) in sizes:
        app.geometry("%dx%d" % (W, H))
        spin(app, 0.3)
        for dstate in doc_states:
            app.set_document(dstate() if callable(dstate) else dstate)
            for key in keys:
                app.show(key)
                spin(app, 0.35)
                iss = probe_panel(app, key)
                if iss:
                    spin(app, 0.7)             # розкладка могла ще встигати за подіями: звітуємо лише про те, що не минуло
                    iss = probe_panel(app, key)
                if iss:
                    result[((W, H), "doc" if dstate else "nodoc", key)] = iss
    return result


def format_report(result):
    lines = []
    for (size, ds, key), iss in sorted(result.items(), key=lambda kv: str(kv[0])):
        for path, cls, text, probs in iss:
            lines.append("%dx%d %s %s: %s %s «%s»: %s" % (size[0], size[1], ds, key, path[-60:], cls, text, "; ".join(probs)))
    return lines


def main():
    import tempfile
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings
    import test_cps_csv as tc
    from cps_ui import document as D
    tmp = tempfile.mkdtemp(prefix="probe_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    try:
        spi = tc.make_fixture_spi()
        cp, _d = tc.codeplug_of(spi)
        res = run_all(app, doc_states=(None, lambda: D.Document(cp, D.ORIGIN_FILE, source_file="тест.zip")))
        for l in format_report(res):
            print(l)
        print("Проблем: %d" % sum(len(v) for v in res.values()))
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
