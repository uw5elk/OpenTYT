/* AES-fix6 G1/G2: класифікація PI-burst-ів ДО стокового фільтра hrc6000SysReceivedDataInt (dmr_aes_hook.c, -DDMR_AES_DIAG_RX).
 *
 * Тест #include-ить СПРАВЖНІЙ dmr_aes_hook.c і перевіряє логіку, яку HR-C6000.c викликає перед фільтром:
 *  - лічильники (сирий біт, обнулення перекриттям «ключ завантажено», причина відкидання PI/CRC/колір-код, dataType 0);
 *  - режим 0 (типовий) НІКОЛИ не вимагає віддати LC у dmrAesRxPI -- чистий замір (перебір усіх комбінацій входів);
 *  - режим 1: лише burst, відкинутий гілкою PI при нормальних CRC і колір-коді; режим 2: + data-sync dataType 0 з невалідним CRC (колір-код ок);
 *  - кільця: сирий біт -> кільце 0, data-sync dt0 -> кільце 1, обидва -> обидва; обгортання; прапорець «віддано»;
 *  - формат дампу USB 0x87 (магія, розміри, влазить у COM_BUFFER_SIZE), reset чистить лічильники й кільця, але НЕ режим; dmrAesInit скидає режим.
 * Саму гілку фільтра в HR-C6000.c (return до hrc6000HandleLCData) тест не виконує -- вона лишається стоковою. */
#include "../application/source/crypto/dmr_aes_hook.c"

#include <stdio.h>
#include <stdlib.h>

CodeplugChannel_t *currentChannelData = NULL;
bool SPI_Flash_read(uint32_t a, uint8_t *b, int n) { (void)a; memset(b, 0xFF, (size_t)n); return true; }
bool SPI_Flash_write(uint32_t a, uint8_t *b, int n) { (void)a; (void)b; (void)n; return true; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *d, int m) { (void)t; (void)d; (void)m; return false; }
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *d, int l) { (void)t; (void)d; (void)l; return false; }

#ifndef DMR_AES_DIAG_RX
int main(void) { printf("пропуск: потрібен -DDMR_AES_DIAG_RX\n"); return 0; }
#else
static uint32_t g_ms = 1000;
uint32_t ticksGetMillis(void) { return g_ms; }
void hrc6000DiagOursLC(uint8_t lc12[12]) { memset(lc12, 0, 12); }

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { g_fail++; printf("  ПРОВАЛ: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint8_t D[512];
static uint16_t cnt(int i) { return s_pifCnt[i]; }

int main(void)
{
    uint8_t lc[12];
    int fl;
    dmrAesInit();
    dmrAesResetRxDiag();

    /* 1. порожній дамп: розкладка */
    int n = dmrAesGetPiDiag(D, (int)sizeof D);
    CHECK(n == 8 + PIF_CNT_N * 2 + 2 * PIF_N * 18, "довжина дампу %d", n);
    CHECK(D[0] == 0xB6 && D[1] == 1 && D[2] == 0 && D[4] == PIF_N && D[5] == 18 && D[6] == 0 && D[7] == 0, "заголовок дампу");
    CHECK(n <= 512 * 3 - 3, "дамп %d не влазить у COM_BUFFER_SIZE-3", n);
    CHECK(dmrAesGetPiDiag(D, n - 1) == 0, "малий буфер -> 0");

    /* 2. режим 0, ключа нема: PI-burst у RX_x, CRC і колір-код ок -> відкинуто ЛИШЕ через PI; лише LOG, жодного FEED */
    fl = dmrAesDiagPiClassify(1, 1, 1, 1, 1, 1, 1);
    CHECK((fl & PIF_LOG) && !(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 0: fl=%x", fl);
    CHECK(cnt(PIFC_INTS) == 1 && cnt(PIFC_RAWPI) == 1 && cnt(PIFC_CLEARED) == 0 && cnt(PIFC_DROP) == 1 &&
          cnt(PIFC_DROP_PI) == 1 && cnt(PIFC_DROP_PI_ONLY) == 1 && cnt(PIFC_DROP_CRC) == 0 && cnt(PIFC_DROP_CC) == 0, "лічильники PI-гілки");
    CHECK((fl & 0x7F) == (1 | 0x04 | 0x08 | 0x10 | 0x20 | 0x40), "прапорці запису %x", fl & 0x7F);

    /* 3. «ключ завантажено»: сирий біт 1, а після перекриття 0 -> фільтр PI не спрацьовує; обнулення пораховане */
    fl = dmrAesDiagPiClassify(1, 1, 1, 1, 0, 1, 1);
    CHECK((fl & PIF_LOG), "сирий біт -> кандидат");
    CHECK(cnt(PIFC_RAWPI) == 2 && cnt(PIFC_CLEARED) == 1 && cnt(PIFC_DROP) == 1 && cnt(PIFC_DROP_PI) == 1, "обнулення ключем: клир=%u drop=%u", cnt(PIFC_CLEARED), cnt(PIFC_DROP));

    /* 4. не PI-burst, не dataType 0: нічого не логуємо, лише лічильник переривань */
    fl = dmrAesDiagPiClassify(3, 1, 1, 0, 0, 1, 1);
    CHECK(!(fl & PIF_LOG), "звичайний голосовий burst не кандидат");
    CHECK(cnt(PIFC_INTS) == 3, "ints");

    /* 5. dataType 0 (data-sync): кандидат і без біта; у режимі 0 не віддається; лічильники dt0 */
    dmrAesResetRxDiag();
    fl = dmrAesDiagPiClassify(0, 2, 1, 0, 0, 0, 1);   /* CRC невалідний -> фільтр відкине */
    CHECK((fl & PIF_LOG) && !(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "dt0 режим 0");
    CHECK(cnt(PIFC_DT0) == 1 && cnt(PIFC_DT0_DROP) == 1 && cnt(PIFC_DROP_CRC) == 1 && cnt(PIFC_DROP_PI) == 0, "dt0 лічильники");
    fl = dmrAesDiagPiClassify(0, 1, 1, 0, 0, 0, 1);   /* dataType 0 у voice-sync (seq F=0?) -- НЕ PI Header */
    CHECK(!(fl & PIF_LOG), "dt 0 з syncClass 1 -- не кандидат");

    /* 6. режим 0 ніколи не вимагає FEED: перебір усіх комбінацій входів */
    dmrAesDiagPiSetMode(0);
    int bad = 0;
    for (int m = 0; m < 4 * 2 * 2 * 2 * 2 * 2 * 2; m++)
    {
        uint8_t dt = (m & 1) ? 0 : 7, sc = (uint8_t)((m >> 1) & 3), rx = (m >> 3) & 1, pr = (m >> 4) & 1, pe = (m >> 5) & 1, cr = (m >> 6) & 1, cc = (m >> 7) & 1;
        if (pe && !pr) { continue; }   /* ефективний PI не буває без сирого */
        if (dmrAesDiagPiClassify(dt, sc, rx, pr, pe, cr, cc) & (PIF_FEED_PI | PIF_FEED_DT0)) { bad++; }
    }
    CHECK(bad == 0, "режим 0 просив FEED %d разів", bad);

    /* 7. режим 1 */
    dmrAesDiagPiSetMode(1);
    fl = dmrAesDiagPiClassify(5, 1, 1, 1, 1, 1, 1);
    CHECK(fl & PIF_FEED_PI, "режим 1: PI-гілка, CRC і колір-код ок -> FEED");
    fl = dmrAesDiagPiClassify(5, 1, 1, 1, 1, 0, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 1: CRC невалідний -> без FEED (як і стокове читання LC)");
    fl = dmrAesDiagPiClassify(5, 1, 1, 1, 1, 1, 0);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 1: чужий колір-код -> без FEED");
    fl = dmrAesDiagPiClassify(5, 1, 0, 1, 1, 1, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 1: слот не RX_x (фільтр не діє) -> без FEED");
    fl = dmrAesDiagPiClassify(5, 1, 1, 1, 0, 1, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 1: ключ завантажено, PI-гілка не спрацювала -> без FEED");
    fl = dmrAesDiagPiClassify(0, 2, 1, 0, 0, 0, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 1: dt0 з невалідним CRC -- ще не режим 2");

    /* 8. режим 2 */
    dmrAesDiagPiSetMode(2);
    fl = dmrAesDiagPiClassify(0, 2, 1, 0, 0, 0, 1);
    CHECK(fl & PIF_FEED_DT0, "режим 2: dt0, CRC невалідний, колір-код ок -> FEED");
    fl = dmrAesDiagPiClassify(0, 2, 1, 0, 0, 0, 0);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 2: dt0 чужого колір-коду -> без FEED");
    fl = dmrAesDiagPiClassify(0, 2, 1, 0, 0, 1, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 2: dt0 з валідним CRC проходить фільтр сам -- без дубля");
    fl = dmrAesDiagPiClassify(0, 2, 0, 0, 0, 0, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 2: не RX_x -> без FEED");
    fl = dmrAesDiagPiClassify(9, 2, 1, 0, 0, 0, 1);
    CHECK(!(fl & (PIF_FEED_PI | PIF_FEED_DT0)), "режим 2: dataType != 0 з невалідним CRC -> без FEED");
    dmrAesDiagPiSetMode(77);
    CHECK(s_pifMode == 2, "режим обмежується 2");

    /* 9. кільця */
    dmrAesResetRxDiag();
    CHECK(s_pifMode == 2, "reset НЕ чіпає режим G2");
    for (int i = 0; i < 12; i++) { lc[i] = (uint8_t)(0x10 + i); }
    g_ms = 5000;
    fl = dmrAesDiagPiClassify(5, 1, 1, 1, 1, 1, 1);          /* сирий біт, голос -> кільце 0, FEED */
    dmrAesDiagPiLog(fl, 5, 1, lc);
    CHECK(s_pifW[0] == 1 && s_pifW[1] == 0, "кільце 0 лише");
    CHECK(s_pif[0][0].dt == 5 && s_pif[0][0].slot == 1 && s_pif[0][0].ts == 5000 && (s_pif[0][0].flags & 0x80) && !memcmp(s_pif[0][0].lc, lc, 12), "запис кільця 0");
    CHECK(cnt(PIFC_FED_PI) == 1 && cnt(PIFC_FED_DT0) == 0, "лічильник FED_PI");
    fl = dmrAesDiagPiClassify(0, 2, 1, 0, 0, 0, 1);          /* dt0, без біта -> кільце 1, FEED_DT0 */
    dmrAesDiagPiLog(fl, 0, 2, lc);
    CHECK(s_pifW[0] == 1 && s_pifW[1] == 1 && (s_pif[1][0].flags & 3) == 2 && (s_pif[1][0].flags & 0x80) && !(s_pif[1][0].flags & 0x08), "запис кільця 1: %x", s_pif[1][0].flags);
    CHECK(cnt(PIFC_FED_DT0) == 1, "лічильник FED_DT0");
    fl = dmrAesDiagPiClassify(0, 2, 1, 1, 0, 1, 1);          /* dt0 і сирий біт, ключ -> в обидва кільця, без FEED */
    dmrAesDiagPiLog(fl, 0, 2, lc);
    CHECK(s_pifW[0] == 2 && s_pifW[1] == 2 && !(s_pif[0][1].flags & 0x80), "обидва кільця, без FEED");
    for (int i = 0; i < 6; i++) { lc[0] = (uint8_t)i; dmrAesDiagPiLog(dmrAesDiagPiClassify(5, 1, 1, 1, 1, 1, 1) & ~(PIF_FEED_PI | PIF_FEED_DT0), 5, 1, lc); }
    CHECK(s_pifW[0] == 8, "вільнобіжний індекс кільця 0: %u", s_pifW[0]);
    CHECK(s_pif[0][(8 - 1) % PIF_N].lc[0] == 5, "останній запис кільця на місці (w-1)%%N");

    /* 10. дамп після записів, потім reset */
    n = dmrAesGetPiDiag(D, (int)sizeof D);
    CHECK(D[2] == 2 && D[6] == 8 && D[7] == 2, "дамп: режим, W");
    CHECK((D[8 + PIFC_INTS * 2] | (D[9 + PIFC_INTS * 2] << 8)) == cnt(PIFC_INTS) && cnt(PIFC_INTS) > 0, "лічильник у дампі");
    CHECK(!memcmp(D + 8 + PIF_CNT_N * 2, s_pif, sizeof s_pif), "кільця у дампі");
    dmrAesResetRxDiag();
    n = dmrAesGetPiDiag(D, (int)sizeof D);
    int allz = 1;
    for (int i = 6; i < n; i++) { if (i == 6 || i == 7 || i >= 8) { if (D[i]) { allz = 0; } } }
    CHECK(allz && D[2] == 2, "reset чистить лічильники й кільця, режим лишається");
    dmrAesInit();
    CHECK(s_pifMode == 0, "dmrAesInit скидає режим G2 у 0");

    if (g_fail) { printf("ПРОВАЛ test_aes_pifilter: %d\n", g_fail); return 1; }
    printf("ok test_aes_pifilter\n");
    return 0;
}
#endif
