# -*- coding: utf-8 -*-
"""R75: запис ДОКУМЕНТА в рацію однією дією (без Tk; викликається з doc_actions і з хост-тестів).

Порядок: перевірки -> план налаштувань (відмова ДО будь-якого запису) -> страхова копія області налаштувань -> кодплаг через
cps_csv.write_image_via_restore / cps_restore.restore_codeplug (один діалог «що зміниться», страхова копія, лише відмінні сектори, SHA-256)
-> налаштування через custom_region.apply_plan (групи по секторах, sector-safe, звірка читанням) -> ОДНЕ перезавантаження (C 6 1).
Нових доріг запису в обхід cps_restore / custom_region / flash_guard нема.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import codeplug_view as cpview  # noqa: E402
import cps_csv as cc  # noqa: E402
import cps_link as cps  # noqa: E402
import cps_restore as cps_rest  # noqa: E402
import custom_region as creg  # noqa: E402
import doc_region as dreg  # noqa: E402
import phase_timing  # noqa: E402

WRITE_TITLE = "ЗАПИС З ДОКУМЕНТА -- рація буде ПЕРЕЗАПИСАНА."


def write_document(link, d, confirm, progress, out_dir, log=print):
    """confirm(text[, plan]) -> bool; progress(percent, text). Повертає словник (див. doc_actions._doc_written): ключі importZip/safetyCopy --
    коли відпрацював restore_codeplug; regionResult -- коли писались налаштування; regionWritten; written_image; cancelled; nothingToDo."""
    info = link.radio_info()
    reason = d.write_block_reason(info)
    if reason:
        raise cps.CpsError("{} Нічого не записано.".format(reason))
    img_pending = d.image_pending()
    plan = region_cur = safety = None
    blocks = d.region_write_blocks()
    if blocks:
        region_cur = creg.read_radio_region(link)
        try:
            plan = dreg.plan_for_radio(blocks, region_cur)
        except creg.RegionError as e:
            raise cps.CpsError("Налаштування записати не можна: {} Нічого не записано.".format(e))
        if plan.refused():
            raise cps.CpsError("Налаштування записати не можна:\n{}\nНічого не записано.".format(dreg.plan_text(plan)))
        if plan.writes():
            safety = dreg.save_safety(region_cur, out_dir)          # ДО першого запису чого завгодно
            log("Страхова копія налаштувань рації: {}".format(safety))
        else:
            plan = None
    if not img_pending and plan is None:
        return {"nothingToDo": True, "written_image": d.image, "regionWritten": True}
    region_lines = dreg.plan_lines(plan) if plan is not None else []
    out = {"regionWritten": True}
    if img_pending:
        fresh, share, prefetched = None, 0, None
        ph = phase_timing.Phases(link)
        if d.origin == "radio":
            log("Читаю свіжий стан рації: на нього накладуться лише ваші зміни, а не весь застарілий образ.")
            with ph.phase("свіже читання рації"):
                cp, _m = cpview.codeplug_from_radio(link, lambda p, t: progress(int(p * 0.25), t))
            fresh = cc.Image.from_codeplug(cp)
            prefetched = (cp.eeprom, cp.flash)      # R32 T2.2: страхова копія візьме звідси EEPROM і флеш, а не читатиме їх вдруге
            share = 25
        res, conflicts = d.write_image(fresh)
        if conflicts:
            log("Конфліктів зі змінами рації: {}.".format(conflicts))
        # у діалозі налаштування описує ПЛАН (що справді буде записано), а не журнал правок документа
        for lst in (res.added, res.changed, res.removed):
            lst[:] = [x for x in lst if x[0] != "Налаштування"]
        for kind, sec, text in region_lines:
            getattr(res, kind).append((sec, text))
        out = cc.write_image_via_restore(
            link, res, confirm, lambda p, t: progress(share + int(p * (100 - share) / 100.0), t), log=log,
            title=WRITE_TITLE, out_dir=out_dir, zip_prefix="codeplug_document-write",
            note="Образ, зібраний із документа кодплага. Це те, що буде записано.", prefetched=prefetched, phases=ph,
            post_reset=(plan is None))
        out["written_image"] = res.image
        out["regionWritten"] = True
        if out.get("cancelled"):
            return out
    else:
        text = ("ЗАПИС НАЛАШТУВАНЬ -- рація буде змінена. Кодплаг не чіпається.\n\nЩо зміниться:\n" + dreg.plan_text(plan) +
                "\n\nПеред записом поточні налаштування рації збережено у файл: " + str(safety) +
                "\nБлоки пишуться по одному зі звіркою читанням; після запису рація перезавантажиться.")
        if not confirm(text):
            return {"cancelled": True, "nothingToDo": False, "written_image": d.image, "regionWritten": False,
                    "text": "Скасовано; нічого не записано."}
        out["written_image"] = d.image
    if plan is not None:
        rres = dreg.write_region(link, plan, region_cur, safety=safety, log=log, progress=lambda p, t: progress(int(p), t), post_reset=False)
        out["regionResult"] = rres
        out["regionWritten"] = not rres.get("failed") and rres.get("regionMatchesExpected") is not False
        if rres["written"] or (img_pending and not out.get("nothingToDo")):
            cps_rest._send_c(link, 6, cps_rest.POST_RESTORE_SUB)          # одне перезавантаження наприкінці (кодплаг і налаштування)
    return out
