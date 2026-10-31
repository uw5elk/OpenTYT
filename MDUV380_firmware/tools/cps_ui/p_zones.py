# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Зони» (CPS-fix2, T2): зони документа -- до 80 каналів у кожній (формат кодплага 16 каналів теж підтримано: ліміт
береться з документа), порядок має значення. Один канал може бути в кількох зонах. Перевірки -- ті самі, що в імпорті CSV (table_edit.py)."""
import gui_dialogs as gd
import table_edit as te

from .editor_base import MembersEditor


class ZonesPanel(MembersEditor):
    key = "zones"
    title = "Зони"
    kind = "zone"
    noun = "зона"
    members_noun = "каналів"
    members_where = "зоні"
    hint_text = ("Зони: набори каналів для перемикання на рації. До 80 каналів у зоні, порядок має значення; той самий канал може бути "
                 "в кількох зонах. Зміни потрапляють у документ одразу; рація змінюється лише за дією «Записати кодплаг у рацію».")
    columns = (("name", "Назва", 190, True), ("count", "Каналів", 70, False))

    def entities(self, img):
        return [(b, (name, len(mem))) for b, name, mem in te.zones(img)]

    def candidates(self, img):
        return [(n, "№%d %s · %s" % (n, name, rx)) for n, name, _ty, rx in te.channels(img, self.dp)]

    def members(self, img, ident):
        return dict((b, mem) for b, _n, mem in te.zones(img)).get(ident, [])

    def limit(self, img):
        return te.zone_limit(img)

    def ask_new(self, img):
        items = self.candidates(img)
        if not items:
            self.show_message("У кодплазі нема каналів -- спершу додайте канал у розділі «Канали».", "err")
            return None
        got = gd.pick_dialog(self.shell, "Нова зона", "Назва зони:", items, te.zone_limit(img),
                             check=lambda t: te.name_problem(img, "zone", t), ok="Створити", noun="каналів")
        if got is None:
            return None
        name, nums = got
        return lambda im: te.add_entity(im, "zone", name, nums, self.dp)
