/* AES-fix2: фаза шифрування TX привязана до позиції burst в ефірі (B1), пропуск розшифровки канонічної тиші на RX (B3).
 *
 * Тест #include-ить СПРАВЖНІЙ application/source/crypto/dmr_aes_hook.c. Залізо моделюється так, як воно влаштоване у
 * HR-C6000.c: кодувальник (dmrAesTxCodecFrame + dmrAesTxStuffMI, по кадру) кладе кадри в чергу; на кожному голосовому
 * слоті ISR бере з черги 3 кадри, а коли їх менше 3 -- шле в ефір SILENCE_AUDIO і викликає dmrAesTxSkipBurst().
 * Приймач -- справжній dmrAesRxPI/RxBurst/RxLateEntry/RxCodecFrame (порядок як у HR-C6000.c), фаза ключового потоку
 * береться з seq слота, тобто з ефіру.
 *
 * Властивість, що перевіряється (T1/T2): кожен кадр, який НЕ стояв у черзі в мить тихого burst-а, лягає в ефір на ту ж
 * позицію (mod 18), що й фаза, з якою його зашифровано, nibble late entry лежить у (vc = txSequence+1, cw = індекс кадру в
 * burst), MI кадру збігається з MI його суперфрейму, а приймач його розшифровує. Кадри, що стояли в черзі (<= 2 на кожен
 * тихий burst), -- відомі втрати, їх число не більше 2 на тихий burst.
 *
 * Збирається тричі (tests/run_tests.sh): звичайно; з -DAES_TX_MI_CURRENT; з -DAES_TX_PHASE_FIX_OFF -- тоді тест ІНВЕРТОВАНИЙ:
 * він має ЗНАЙТИ зсув (T3: тест здатен побачити дефект), і успіхом вважається саме знайдений дефект. */
#include "../application/source/crypto/dmr_aes_hook.c"

#include <stdio.h>
#include <stdlib.h>

/* ---- заглушки заліза ---- */
CodeplugChannel_t *currentChannelData = NULL;
bool SPI_Flash_read(uint32_t a, uint8_t *b, int n) { (void)a; memset(b, 0xFF, (size_t)n); return true; }
bool SPI_Flash_write(uint32_t a, uint8_t *b, int n) { (void)a; (void)b; (void)n; return true; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *d, int m) { (void)t; (void)d; (void)m; return false; }
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *d, int l) { (void)t; (void)d; (void)l; return false; }
#ifdef DMR_AES_DIAG_RX
uint32_t ticksGetMillis(void) { return 0; }
#endif

#define KEYID 1
#define MAXB  80            /* голосових слотів у сценарії */
#define MAXF  (MAXB * 3 + 64)

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { g_fail++; printf("  ПРОВАЛ: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* канонічна тиша -- копія HR-C6000.c SILENCE_AUDIO (там вона static) */
static const uint8_t SIL[27] = {
    0xB9,0xE8,0x81,0x52,0x61,0x73,0x00,0x2A,0x6B, 0xB9,0xE8,0x81,0x52,0x61,0x73,0x00,0x2A,0x6B, 0xB9,0xE8,0x81,0x52,0x61,0x73,0x00,0x2A,0x6B };

static uint32_t g_rng = 0x9E3779B9u;
static uint32_t rnd(void) { g_rng = g_rng * 1664525u + 1013904223u; return g_rng >> 8; }

typedef struct {
    uint16_t pl[49], ct[49];
    uint8_t  nib;           /* 4 біти late entry, які StuffMI поклав у кодове слово */
    uint32_t cnt;           /* лічильник шифрування (s_txFrameCnt у мить кодування) */
    int      tainted;       /* стояв у черзі в мить тихого burst-а */
    uint32_t mi;            /* s_tx.mi після кодування */
} fr_t;

typedef struct {
    int silent;             /* тихих burst-ів у сценарії */
    int voiceFrames;        /* кадрів, що пішли в ефір */
    int untainted, untaintedBadPhase, untaintedBadVc, untaintedBadMi, untaintedBadRx;
    int tainted, taintedMax;/* кадрів у черзі в мить тихого burst-а (сума) / максимум на один тихий */
    int mismatchK0;         /* кадрів зі зсувом k != 0 (усіх) */
} stats_t;

/* prod[b] -- скільки кадрів кодувальник встигає видати ДО слота b; n -- число слотів */
static void run_sim(const int *prod, int n, uint32_t mi0, stats_t *st)
{
    static fr_t fifo[MAXF];
    uint8_t key[32];
    for (int i = 0; i < 32; i++) key[i] = (uint8_t)(i * 7 + 3);
    memset(st, 0, sizeof *st);
    dmrAesInit();
    dmrAesSetKeyRam(KEYID, key);
    dmrAesTxStart(KEYID, mi0);
    uint8_t pi[7];
    if (dmrAesTxBuildPI(pi) != 7) { printf("TX не активний\n"); exit(2); }
    dmrAesRxPI(pi, 7); dmrAesRxPI(pi, 7);                 /* засіяти приймач двома однаковими PI */

    uint32_t mi[16]; mi[0] = mi0;                          /* MI суперфреймів: PI-MI, далі LFSR */
    for (int i = 0; i < 15; i++) { uint8_t iv[16]; dmr_lfsr128d(mi[i], iv, &mi[i + 1]); }

    int head = 0, tail = 0;                                /* черга: кадри [head, tail) */
    int airFrame = 0;
    for (int b = 0; b < n; b++)
    {
        for (int k = 0; k < prod[b] && tail < MAXF; k++)   /* кодувальник */
        {
            fr_t *f = &fifo[tail++];
            for (int i = 0; i < 49; i++) { f->pl[i] = (uint16_t)(rnd() & 1); }
            f->pl[24] = 0; f->pl[30] = 1;                  /* не «комфортний шум» і не тиша */
            memcpy(f->ct, f->pl, sizeof f->pl);
            dmrAesTxCodecFrame(f->ct);
            uint16_t b72[72] = {0};
            dmrAesTxStuffMI(b72);
            f->nib = (uint8_t)((b72[71] << 3) | (b72[67] << 2) | (b72[63] << 1) | b72[59]);
            f->cnt = s_txFrameCnt - 1; f->tainted = 0; f->mi = s_tx.mi;
        }
        int seq = b % 6;                                   /* txSequence */
        uint8_t ambe27[27];
        uint16_t outb[3][49];
        int voice = ((tail - head) >= 3);
        if (voice)
        {
            memset(ambe27, 0, sizeof ambe27);
            for (int j = 0; j < 3; j++)
            {
                fr_t *f = &fifo[head + j];
                uint8_t *c = ambe27 + j * 9;
                if (f->nib & 8) c[8] |= 0x01;
                if (f->nib & 4) c[8] |= 0x10;
                if (f->nib & 2) c[7] |= 0x01;
                if (f->nib & 1) c[7] |= 0x10;
                memcpy(outb[j], f->ct, sizeof f->ct);
            }
        }
        else
        {
            memcpy(ambe27, SIL, sizeof SIL);
            for (int j = 0; j < 3; j++) for (int i = 0; i < 49; i++) outb[j][i] = (uint16_t)(rnd() & 1);
            for (int q = head; q < tail; q++) fifo[q].tainted = 1;   /* вони пройдуть на 3 кадри пізніше */
            int pend = tail - head;
            st->tainted += pend; if (pend > st->taintedMax) st->taintedMax = pend;
            st->silent++;
#ifdef DMR_AES_DIAG_RX
            dmrAesDiagTxBurst(seq, 1);
#endif
            if (dmrAesTxActive()) { dmrAesTxSkipBurst(); }
        }

#ifdef DMR_AES_DIAG_RX
        if (voice) { dmrAesDiagTxBurst(seq, 0); }
#endif
        /* ---- приймач: порядок як у HR-C6000.c ---- */
        dmrAesRxBurst(seq + 1);
        dmrAesRxLateEntry(seq + 1, ambe27);
        int silentBlk = dmrAesRxActive() && dmrAesRxIsSilence(ambe27, SIL);
        CHECK(silentBlk == !voice, "слот %d: класифікація тиші приймачем (%d) != фактичній (%d)", b, silentBlk, !voice);
        dmrAesRxSilentBlock(silentBlk);
        for (int j = 0; j < 3; j++)
        {
            uint16_t dec[49]; memcpy(dec, outb[j], sizeof dec);
            dmrAesRxCodecFrame(dec, j);
            if (voice)
            {
                fr_t *f = &fifo[head + j];
                int air = airFrame + j;                    /* глобальна позиція кадру в ефірі */
                int phaseOk = ((int)(f->cnt % 18) == (air % 18));
                int vcOk = ((int)((f->cnt / 3) % 6) == seq);            /* StuffMI: vc-1 == txSequence */
                int cwOk = ((int)(f->cnt % 3) == j);                    /* StuffMI: cw == індекс кадру в burst */
                int miOk = (f->mi == mi[f->cnt / 18]);
                int rxOk = (memcmp(dec, f->pl, sizeof dec) == 0);
                if (!phaseOk) st->mismatchK0++;
                if (!f->tainted)
                {
                    st->untainted++;
                    if (!phaseOk) st->untaintedBadPhase++;
                    if (!(vcOk && cwOk)) st->untaintedBadVc++;
                    if (!miOk) st->untaintedBadMi++;
                    if (!rxOk) st->untaintedBadRx++;
                }
            }
            else
            {
                CHECK(memcmp(dec, outb[j], sizeof dec) == 0, "слот %d: приймач розшифрував кадр тиші (B3)", b);
            }
        }
        dmrAesRxSilentBlock(0);
        if (voice) { head += 3; airFrame += 3; st->voiceFrames += 3; } else { airFrame += 3; }
    }
}

static void show(const char *name, const stats_t *s)
{
    printf("  %-44s тихих=%d  кадрів в ефір=%d  без черги: %d (фаза-%d, vc/cw-%d, MI-%d, RX-%d)  у черзі на тихих: %d (макс %d)\n",
           name, s->silent, s->voiceFrames, s->untainted, s->untaintedBadPhase, s->untaintedBadVc, s->untaintedBadMi,
           s->untaintedBadRx, s->tainted, s->taintedMax);
}

/* Очікування для звичайної збірки: жодного зсуву у кадрів, що не стояли в черзі; у черзі на кожен тихий <= 2 */
static void expect_fixed(const char *name, const stats_t *s)
{
    show(name, s);
    CHECK(s->untaintedBadPhase == 0, "%s: фаза шифрування != позиції в ефірі у %d кадрів", name, s->untaintedBadPhase);
    CHECK(s->untaintedBadVc == 0,    "%s: nibble late entry (vc,cw) не збігся з txSequence/індексом у %d кадрів", name, s->untaintedBadVc);
    CHECK(s->untaintedBadMi == 0,    "%s: MI кадру != MI суперфрейму в %d кадрів", name, s->untaintedBadMi);
    CHECK(s->untaintedBadRx == 0,    "%s: приймач не розшифрував %d кадрів", name, s->untaintedBadRx);
    CHECK(s->taintedMax <= 2,        "%s: у черзі в мить тихого burst було %d (>2)", name, s->taintedMax);
}

int main(void)
{
    stats_t st;
    int prod[MAXB];
#ifdef AES_TX_PHASE_FIX_OFF
    const int fixOff = 1;
    printf("== ЗБІРКА БЕЗ ФІКСУ (AES_TX_PHASE_FIX_OFF): тест ІНВЕРТОВАНИЙ -- має знайти зсув\n");
#else
    const int fixOff = 0;
#endif

    /* S1: типовий старт -- перший голосовий burst тиша, черга порожня (P=0) */
    for (int b = 0; b < MAXB; b++) prod[b] = 3;
    prod[0] = 0;
    run_sim(prod, 30, 0x174E6042u, &st);
    if (fixOff) { show("S1 старт, черга порожня", &st); CHECK(st.untaintedBadPhase > 0 && st.untaintedBadRx > 0, "S1: без фіксу зсуву не знайдено -- тест не бачить дефект"); }
    else { expect_fixed("S1 старт, черга порожня", &st); CHECK(st.silent == 1 && st.voiceFrames == 29 * 3, "S1: очікувалось 1 тихий burst"); }

#ifdef DMR_AES_DIAG_RX
    {   /* B0/B2: дамп діагностики відбиває те саме, що тест бачить напряму (хвіст після кільця, зсув 8 хвоста) */
        static uint8_t dump[2048];
        int nn = dmrAesGetRxDiag(dump, (int)sizeof dump);
        int hdr = 32, body = (int)sizeof s_rxd, trl = dump[3];
        CHECK(nn == hdr + body + trl && trl == 8 + 10 + 2 * TXD_FR, "дамп: довжина %d, хвіст %d", nn, trl);
        const uint8_t *t = dump + hdr + body + 8;
        int silent = t[0] | (t[1] << 8), bursts = t[4] | (t[5] << 8), enc = t[6] | (t[7] << 8), cons = t[8] | (t[9] << 8);
        printf("  B0 дамп: тихих=%d перший txSequence=%d (burst №%d) усього burst=%d закодовано=%d в ефір=%d\n", silent, t[2], t[3], bursts, enc, cons);
        CHECK(silent == 1 && t[2] == 0 && t[3] == 0, "B0: лічильник тихих/перший txSequence у дампі");
        CHECK(bursts == 30 && cons == 29 * 3, "B0: усього burst-ів/кадрів у дампі");
        int kbad = 0, kcnt = 0;
        for (int i = 0; i < TXD_FR; i++)
        {
            int w = t[10 + i * 2] | (t[11 + i * 2] << 8);
            if (!(w & 0x8000)) continue;
            int cnt = (w >> 8) & 0x7F, pos = w & 0xFF, k = ((pos - cnt) % 18 + 18) % 18;
            kcnt++;
#ifdef AES_TX_PHASE_FIX_OFF
            if (k != 3) kbad++;
#else
            if (k != 0) kbad++;
#endif
        }
        printf("  B2 дамп: пар %d, невідповідних очікуваному зсуву (%s): %d\n", kcnt, fixOff ? "k=3" : "k=0", kbad);
        CHECK(kcnt == TXD_FR && kbad == 0, "B2: зсув фази в дампі не такий, як очікувалось");
    }
#endif

    /* S2: старт, у черзі вже 2 кадри (P=2) -- вони постраждають, усі наступні мають бути в нормі */
    for (int b = 0; b < MAXB; b++) prod[b] = 3;
    prod[0] = 2; prod[1] = 4;
    run_sim(prod, 30, 0xA5335998u, &st);
    if (fixOff) show("S2 старт, у черзі 2 кадри", &st); else { expect_fixed("S2 старт, у черзі 2 кадри", &st); CHECK(st.tainted == 2, "S2: очікувалось 2 кадри в черзі на тихому"); }

    /* S3 (T2): тихий burst, що перетинає межу 18 кадрів: лічильник 15 -> 18 (кадр 18 сам робить крок) */
    for (int b = 0; b < MAXB; b++) prod[b] = 3;
    prod[0] = 3; prod[5] = 0;
    run_sim(prod, 40, 0x12345678u, &st);
    if (fixOff) show("S3 тихий на лічильнику 15 (межа 18)", &st); else expect_fixed("S3 тихий на лічильнику 15 (межа 18)", &st);

    /* S4 (T2): лічильник 18 -> 21: межу перестрибнуто, її крок мусить зробити сам пропуск (рівно один) */
    for (int b = 0; b < MAXB; b++) prod[b] = 3;
    prod[6] = 0;
    run_sim(prod, 40, 0x0BADF00Du, &st);
    if (fixOff) show("S4 тихий на лічильнику 18 (перестрибнуто)", &st); else expect_fixed("S4 тихий на лічильнику 18 (перестрибнуто)", &st);

    /* S5: кілька тихих підряд до першого кадру, з перетином межі ще ДО кодування (7 слотів = 21 кадр) */
    for (int b = 0; b < MAXB; b++) prod[b] = 3;
    for (int b = 0; b < 7; b++) prod[b] = 0;
    run_sim(prod, 40, 0x2468ACE0u, &st);
    if (fixOff) show("S5 сім тихих до першого кадру", &st); else { expect_fixed("S5 сім тихих до першого кадру", &st); CHECK(st.silent == 7, "S5: очікувалось 7 тихих"); }

    /* S6: кілька тихих підряд посеред виклику (аккумуляція d>1 між двома кадрами) */
    for (int b = 0; b < MAXB; b++) prod[b] = 3;
    prod[10] = 0; prod[11] = 0; prod[12] = 0; prod[13] = 6;
    run_sim(prod, 50, 0xDEADBEEFu, &st);
    if (fixOff) show("S6 три тихі підряд посеред виклику", &st); else expect_fixed("S6 три тихі підряд посеред виклику", &st);

    /* S7: випадкові underrun-и (кодувальник то встигає, то ні): 300 прогонів, різні MI */
    int totalSilent = 0, totalUntaintedBad = 0, runs = 300;
    for (int r = 0; r < runs; r++)
    {
        for (int b = 0; b < 60; b++)
        {
            uint32_t x = rnd() % 10;
            prod[b] = (x < 5) ? 3 : (x < 7) ? 0 : (x < 8) ? 1 : (x < 9) ? 2 : 5;
        }
        run_sim(prod, 60, rnd(), &st);
        totalSilent += st.silent;
        totalUntaintedBad += st.untaintedBadPhase + st.untaintedBadVc + st.untaintedBadMi + st.untaintedBadRx;
        if (!fixOff) { if (st.untaintedBadPhase || st.untaintedBadVc || st.untaintedBadMi || st.untaintedBadRx || st.taintedMax > 2) { expect_fixed("S7 випадковий прогін", &st); break; } }
    }
    printf("  S7 випадкові underrun-и: %d прогонів, тихих burst-ів %d, порушень у кадрах без черги: %d\n", runs, totalSilent, totalUntaintedBad);
    if (fixOff) { CHECK(totalUntaintedBad > 0, "S7: без фіксу порушень не знайдено"); }

    /* ---- B3: розпізнавання канонічної тиші ---- */
    {
        uint8_t blk[27]; memcpy(blk, SIL, 27);
        int ok = dmrAesRxIsSilence(blk, SIL);
        for (int cw = 0; cw < 3; cw++) { blk[cw * 9 + 8] ^= 0x11; blk[cw * 9 + 7] ^= 0x11; }   /* біти late entry стокова може класти й у тишу */
        int okMasked = dmrAesRxIsSilence(blk, SIL);
        memcpy(blk, SIL, 27); blk[13] ^= 0x01;                                                     /* будь-який інший біт -- уже не тиша */
        int bad1 = dmrAesRxIsSilence(blk, SIL);
        memcpy(blk, SIL, 27); blk[9 + 3] ^= 0x80;
        int bad2 = dmrAesRxIsSilence(blk, SIL);
        uint8_t voiceBlk[27]; for (int i = 0; i < 27; i++) voiceBlk[i] = (uint8_t)rnd();
        int bad3 = dmrAesRxIsSilence(voiceBlk, SIL);
        printf("  B3: тиша=%d тиша+біти LE=%d  інший біт=%d,%d  голос=%d\n", ok, okMasked, bad1, bad2, bad3);
        CHECK(ok == 1 && okMasked == 1, "B3: канонічна тиша (і з бітами late entry) не розпізнана");
        CHECK(bad1 == 0 && bad2 == 0 && bad3 == 0, "B3: не-тиша прийнята за тишу");
    }

    if (fixOff)
    {
        /* інвертована збірка: «провали» вище -- це якраз знайдений дефект; успіх = тест його побачив */
        printf(g_fail ? "=== ТЕСТ НЕ ПОБАЧИВ ДЕФЕКТ (%d) ===\n" : "ДЕФЕКТ БЕЗ ФІКСУ ЗНАЙДЕНО -- тест здатен його бачити\n", g_fail);
        return g_fail ? 1 : 0;
    }
    printf(g_fail ? "=== ПРОВАЛИ: %d ===\n" : "УСЕ ПРОЙДЕНО\n", g_fail);
    return g_fail ? 1 : 0;
}
