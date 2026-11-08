# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Списки прийому» (CPS-fix2, T1): TG-списки документа -- до 32 контактів у кожному (RXGROUP_MAX_CONTACTS), порядок має
значення. Контакти додаються з загального переліку (дві колонки), межа 32 не дається перевищити з поясненням. Перевірки -- ті самі, що в імпорті CSV
(table_edit.py -> cps_csv.import_csv)."""
import gui_dialogs as gd
import table_edit as te

from .editor_base import MembersEditor


class TgListsPanel(MembersEditor):
    key = "tglists"
    title = "Списки прийому"
    kind = "tg"
    noun = "список прийому"
    members_noun = "контактів"
    members_where = "списку"
    reorderable = True
    hint_text = ("Групи прийому (TG-списки): що рація слухає на цифровому каналі. До %d контактів у списку, порядок має значення. "
                 "Зміни потрапляють у документ одразу; рація змінюється лише за дією «Записати в рацію». «Вище ↑ / Нижче ↓» під таблицею "
                 "(Ctrl+↑ / Ctrl+↓ або перетягування рядка) змінює порядок списків -- канали, що на них посилаються, оновлюються самі; порядок контактів "
                 "У списку -- кнопки «Вгору ↑ / Вниз ↓» між списками." % te.TG_MAX)
    columns = (("name", "Назва", 190, True), ("count", "Контактів", 70, False))

    def entities(self, img):
        return [(s, (name, len(mem))) for s, name, mem in te.tg_lists(img)]

    def candidates(self, img):
        return [(n, "№%d %s · ID %d · %s" % (n, name, cid, ty)) for n, name, cid, ty in te.contacts(img)]

    def members(self, img, ident):
        return dict((s, mem) for s, _n, mem in te.tg_lists(img)).get(ident, [])

    def limit(self, img):
        return te.TG_MAX

    def ask_new(self, img):
        items = self.candidates(img)
        if not items:
            self.show_message("У кодплазі нема контактів -- спершу додайте контакт у «Кодплаг → Контакти».", "err")
            return None
        got = gd.pick_dialog(self.shell, "Новий список прийому", "Назва списку:", items, te.TG_MAX,
                             check=lambda t: te.name_problem(img, "tg", t), ok="Створити", noun="контактів")
        if got is None:
            return None
        name, nums = got
        return lambda im: te.add_entity(im, "tg", name, nums, self.dp)
