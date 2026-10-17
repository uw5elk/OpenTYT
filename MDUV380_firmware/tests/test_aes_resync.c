/* AES-fix1: ресинхронізація MI на прийомі (A1) і симетрія TX<->RX у обох режимах передачі (A2).
 *
 * Тест #include-ить СПРАВЖНІЙ application/source/crypto/dmr_aes_hook.c (щоб бачити його стан: s_rx.mi,
 * s_rxNextMi, s_rxPendValid, s_rxMiFlags), а залізо (SPI-флеш, codeplug) підміняє заглушками. Шифрування
 * справжнє: TX -- dmrAesTxCodecFrame, RX -- dmrAesRxPI/Burst/LateEntry/CodecFrame у тому ж порядку, що й
 * HR-C6000.c (спершу dmrAesRxBurst, потім dmrAesRxLateEntry; потім розшифровка трьох кадрів).
 *
 * Ефір моделюється так: шифротекст усього виклику створюється наперед справжнім TX, а біти late entry
 * збираються тут самим тестом (dmr_le_mi_build) для ОБРАНОЇ конвенції: conv=0 -- MI наступного суперфрейму
 * (look-ahead), conv=1 -- MI поточного. Так обидві конвенції перевіряються в одній збірці. Окремо
 * перевіряється, що ВЛАСНЕ TX-«набивання» (dmrAesTxStuffMI) дає саме ті біти, що типова для цієї збірки
 * конвенція (AES_TX_MI_CURRENT перемикає її) -- це T3.
 *
 * Збірка: tests/run_tests.sh (двічі: звичайна і з -DAES_TX_MI_CURRENT -> test_aes_resync_cur). */
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

#define NSF   40                 /* суперфреймів у виклику */
#define NFR   (NSF * 18)         /* кадрів AMBE */
#define KEYID 1

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { g_fail++; printf("  ПРОВАЛ: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint16_t g_plain[NFR][49], g_ciph[NFR][49];
static uint32_t g_mi[NSF + 4];                  /* MI суперфрейму n: g_mi[0]=PI-MI, далі LFSR */
static uint8_t  g_pi[7];
static uint32_t g_rng = 0x1234567u;
static uint32_t rnd(void) { g_rng = g_rng * 1664525u + 1013904223u; return g_rng >> 8; }

/* Готує виклик: кадри, MI-послідовність, шифротекст справжнім TX. conv_tx=-1: ніяких підмін біт. */
static void make_call(uint32_t mi0)
{
    uint8_t key[32];
    for (int i = 0; i < 32; i++) { key[i] = (uint8_t)(i * 7 + 3); }
    dmrAesInit();
    dmrAesSetKeyRam(KEYID, key);
    g_mi[0] = mi0;
    for (int n = 0; n < NSF + 3; n++) { uint8_t iv[16]; dmr_lfsr128d(g_mi[n], iv, &g_mi[n + 1]); }
    dmrAesTxStart(KEYID, mi0);
    if (dmrAesTxBuildPI(g_pi) != 7) { printf("TX не активний\n"); exit(2); }
    for (int f = 0; f < NFR; f++)
    {
        for (int i = 0; i < 49; i++) { g_plain[f][i] = (uint16_t)(rnd() & 1); }
        g_plain[f][24] = 0;   /* не «комфортний шум» (біти 24..43 не всі одиниці) і не тиша */
        memcpy(g_ciph[f], g_plain[f], sizeof g_plain[f]);
        dmrAesTxCodecFrame(g_ciph[f]);
    }
}

/* Біти late entry одного бурсту суперфрейму n у конвенції conv; bogus!=0 -- підставити чужий MI */
static void le_burst(int n, int vc, int conv, int useBogus, uint32_t bogus, uint8_t ambe27[27])
{
    uint8_t frag[7][3];
    uint32_t mi = useBogus ? bogus : (conv ? g_mi[n] : g_mi[n + 1]);
    dmr_le_mi_build(mi, frag);
    memset(ambe27, 0, 27);
    for (int cw = 0; cw < 3; cw++)
    {
        uint8_t nib = frag[vc][cw];
        uint8_t *c = ambe27 + cw * 9;
        if (nib & 8) c[8] |= 0x01;
        if (nib & 4) c[8] |= 0x10;
        if (nib & 2) c[7] |= 0x01;
        if (nib & 1) c[7] |= 0x10;
    }
}

typedef struct {
    int conv;                 /* конвенція late entry в «ефірі» */
    int usePI;                /* 1 = засіяти приймач PI-LC (двічі) */
    int dropFrom, dropTo;     /* суперфрейми [from,to) приймач не чує зовсім */
    int bogusSf, bogusSf2;    /* суперфрейми з підміненим late entry (-1 нема) */
    uint32_t bogus, bogus2;   /* підмінні значення слів late entry (сирі, як у біт-потоці) */
    int startSf;              /* з якого суперфрейму слухаємо (>0 -- вхід у виклик посередині) */
    int ok[NSF];              /* усі 18 кадрів суперфрейму розшифровано правильно */
    int heard[NSF];
    int miOk[NSF];            /* на початку суперфрейму n: s_rx.mi == справжній MI суперфрейму n */
    int pend[NSF];            /* на початку суперфрейму n: s_rxPendValid */
    uint32_t miAt[NSF];       /* s_rx.mi на початку суперфрейму n */
} run_t;

static int g_lecur = -1;   /* -1 = свіже завантаження; 0/1 = конвенція, вивчена попереднім викликом */

static void run_rx(run_t *r)
{
    uint8_t key[32];
    for (int i = 0; i < 32; i++) { key[i] = (uint8_t)(i * 7 + 3); }
    dmrAesInit();   /* «завантаження»: конвенція за замовчуванням залежить від збірки */
    if (g_lecur >= 0) { s_rxMiFlags = (s_rxMiFlags & ~RXMI_LECUR) | (g_lecur ? RXMI_LECUR : 0); }   /* вивчена раніше: живе між викликами, як у прошивці */
    dmrAesSetKeyRam(KEYID, key);
    if (r->usePI) { dmrAesRxPI(g_pi, 7); dmrAesRxPI(g_pi, 7); }
    for (int n = r->startSf; n < NSF; n++)
    {
        int heard = !(n >= r->dropFrom && n < r->dropTo);
        r->heard[n] = heard;
        r->ok[n] = 1;
        if (!heard) { continue; }
        for (int vc = 1; vc <= 6; vc++)
        {
            uint8_t ambe27[27];
            int useBogus = (n == r->bogusSf) || (n == r->bogusSf2);
            uint32_t bogus = (n == r->bogusSf) ? r->bogus : r->bogus2;
            dmrAesRxBurst(vc);
            if (vc == 1) { r->miAt[n] = (uint32_t)s_rx.mi; r->miOk[n] = (s_rx.mi == g_mi[n]); r->pend[n] = s_rxPendValid; }
            le_burst(n, vc, r->conv, useBogus, bogus, ambe27);
            dmrAesRxLateEntry(vc, ambe27);
            for (int k = 0; k < 3; k++)
            {
                int f = n * 18 + (vc - 1) * 3 + k;
                uint16_t b[49];
                memcpy(b, g_ciph[f], sizeof b);
                dmrAesRxCodecFrame(b, k);
                if (memcmp(b, g_plain[f], sizeof b) != 0) { r->ok[n] = 0; }
            }
        }
    }
    g_lecur = (s_rxMiFlags & RXMI_LECUR) ? 1 : 0;
}

static void init_run(run_t *r, int conv, int usePI)
{
    memset(r, 0, sizeof *r);
    r->conv = conv; r->usePI = usePI;
    r->bogusSf = r->bogusSf2 = -1;
}

/* перший суперфрейм, починаючи з якого ВСІ почуті правильні до кінця виклику */
static int stable_from(const run_t *r)
{
    int s = NSF;
    for (int n = NSF - 1; n >= r->startSf; n--)
    {
        if (r->heard[n] && !r->ok[n]) { break; }
        s = n;
    }
    return s;
}
static int all_ok(const run_t *r)
{
    for (int n = r->startSf; n < NSF; n++) { if (r->heard[n] && !r->ok[n]) return 0; }
    return 1;
}

/* T3: власне TX «набивання» дає біти late entry саме такої конвенції, яка типова для цієї збірки */
static void test_tx_stuffing(void)
{
#ifdef AES_TX_MI_CURRENT
    const int conv = 1;
#else
    const int conv = 0;
#endif
    make_call(0x5A5A1234u);
    /* пройти TX заново, збираючи реально «набиті» біти в ambe27 для кожного бурсту */
    dmrAesTxStart(KEYID, g_mi[0]);
    int bad = 0, total = 0;
    for (int n = 0; n < 8; n++)
    {
        uint8_t got[7][27], want[7][27];
        for (int vc = 1; vc <= 6; vc++)
        {
            memset(got[vc], 0, 27);
            le_burst(n, vc, conv, 0, 0, want[vc]);
            for (int k = 0; k < 3; k++)
            {
                uint16_t b49[49] = {0}, b72[72] = {0};
                for (int i = 0; i < 49; i++) b49[i] = (uint16_t)(rnd() & 1);
                b49[24] = 0;
                dmrAesTxCodecFrame(b49);
                dmrAesTxStuffMI(b72);
                uint8_t *c = got[vc] + k * 9;
                if (b72[71]) c[8] |= 0x01;
                if (b72[67]) c[8] |= 0x10;
                if (b72[63]) c[7] |= 0x01;
                if (b72[59]) c[7] |= 0x10;
            }
            total++;
            if (memcmp(got[vc], want[vc], 27) != 0) bad++;
        }
    }
    printf("== T3 TX-набивання: конвенція збірки = %s; бурстів %d, розбіжностей %d\n", conv ? "ПОТОЧНИЙ MI" : "наступний MI", total, bad);
    CHECK(bad == 0, "T3 TX кладе у late entry не ту конвенцію, що очікує збірка");
}

int main(void)
{
    run_t r;
    test_tx_stuffing();
    for (int conv = 0; conv <= 1; conv++)
    {
        printf("== конвенція late entry в ефірі: %s\n", conv ? "ПОТОЧНИЙ MI" : "наступний MI (look-ahead)");

        /* ---- T0/T3: чистий виклик, засіяний PI: усе розшифровано; конвенцію вивчено ---- */
        make_call(0x174E6042u);
        init_run(&r, conv, 1);
        g_lecur = -1;
        run_rx(&r);
        CHECK(all_ok(&r), "T0 чистий виклик (PI): не всі суперфрейми розшифровано");
        CHECK(((s_rxMiFlags & RXMI_LECUR) != 0) == (conv == 1), "T0 конвенцію вивчено хибно (flags=%d)", s_rxMiFlags);
        CHECK((s_rxMiFlags & RXMI_LELOCK) != 0, "T0 конвенцію не підтверджено");

        /* ---- T3b: чистий виклик БЕЗ PI (швидкий виклик, підняття late entry) у всіх конвенціях ----
         * конвенція береться з попереднього виклику (RXMI_LECUR), що й відбувається в прошивці */
        init_run(&r, conv, 0);
        r.startSf = 3;
        run_rx(&r);
        printf("  T3b виклик без PI: стабільно з суперфрейму %d (початок прослуховування 3)\n", stable_from(&r));
        CHECK(stable_from(&r) <= r.startSf + 3, "T3b виклик без PI не піднявся за 3 суперфрейми");

        /* ---- T1: один суперфрейм випав цілком -> відновлення на наступному late entry ---- */
        make_call(0xA5335998u);
        init_run(&r, conv, 1);
        r.dropFrom = 8; r.dropTo = 9;
        g_lecur = -1;
        run_rx(&r);
        int sf = stable_from(&r);
        printf("  T1 випав суперфрейм #8: стабільно з %d\n", sf);
        for (int n = 0; n < 8; n++) CHECK(r.ok[n], "T1 суперфрейм %d до випадіння мав бути чистим", n);
        CHECK(sf <= r.dropTo + 2, "T1 не відновився за 2 суперфрейми (стабільно з %d)", sf);

        /* ---- T1b: випали 3 суперфрейми поспіль -> відновлення за «двічі поспіль» ---- */
        make_call(0x0BADF00Du);
        init_run(&r, conv, 1);
        r.dropFrom = 8; r.dropTo = 11;
        g_lecur = -1;
        run_rx(&r);
        sf = stable_from(&r);
        printf("  T1b випали суперфрейми #8..10: стабільно з %d\n", sf);
        CHECK(sf <= r.dropTo + 3, "T1b не відновився за 3 суперфрейми (стабільно з %d)", sf);

        /* ---- T1c: контроль «до виправлення»: без ресинхронізації відновлення не було б ----
         * (перевіряємо, що тест взагалі здатний побачити дефект: у gen-режимі -DAES_RESYNC_OFF
         * правило адопту вимкнено в самому тесті через RXMI_PISEEDED=0 -> ні, ми просто фіксуємо,
         * що розбіжність справді виникла: суперфрейм одразу після випадіння не збігається за MI) */
        CHECK(!r.ok[11] || !r.miOk[11], "T1c дефект не відтворено: після випадіння MI збігається одразу");

        /* ---- T2a: поодинокий хибний MI НЕ приймається ---- */
        make_call(0x12345678u);
        init_run(&r, conv, 1);
        r.bogusSf = 10; r.bogus = 0xDEADBEEFu;
        g_lecur = -1;
        run_rx(&r);
        CHECK(all_ok(&r), "T2a поодинокий хибний MI зіпсував розшифровку");
        CHECK(r.miOk[11], "T2a поодинокий хибний MI змінив MI приймача (miAt=%08X)", r.miAt[11]);
        CHECK(r.pend[11], "T2a поодинокий хибний MI мав стати кандидатом (s_rxPendValid=0)");
        CHECK(!r.pend[12], "T2a кандидат мав згаснути після збігу з власним передбаченням");

        /* ---- T2b: узгоджена пара (Y, LFSR(Y)) у двох суперфреймах поспіль -> ПРИЙНЯТО ---- */
        make_call(0x12345678u);
        init_run(&r, conv, 1);
        uint32_t Y = 0xCAFEBABEu, Y2; { uint8_t iv[16]; dmr_lfsr128d(Y, iv, &Y2); }
        r.bogusSf = 10; r.bogus = Y;
        r.bogusSf2 = 11; r.bogus2 = Y2;
        g_lecur = -1;
        run_rx(&r);
        uint32_t want12 = Y2, tmp;
        if (conv) { uint8_t iv[16]; dmr_lfsr128d(Y2, iv, &tmp); want12 = tmp; }   /* «поточний»: MI наступного = LFSR(слова) */
        CHECK(r.pend[11] && r.miOk[11], "T2b після першого з пари MI не мав змінитись");
        CHECK(r.miAt[12] == want12, "T2b пару не прийнято: s_rx.mi(12)=%08X, очікувалось %08X", r.miAt[12], want12);
        sf = stable_from(&r);
        printf("  T2b пару прийнято, далі відновлення: стабільно з %d\n", sf);
        CHECK(sf <= 12 + 4, "T2b після прийнятої хибної пари приймач не повернувся за 4 суперфрейми (стабільно з %d)", sf);

        /* ---- T2c: два однакових хибних MI підряд -- НЕ узгоджена пара -> не приймається ---- */
        make_call(0x12345678u);
        init_run(&r, conv, 1);
        r.bogusSf = 10; r.bogus = Y;
        r.bogusSf2 = 11; r.bogus2 = Y;
        g_lecur = -1;
        run_rx(&r);
        CHECK(all_ok(&r), "T2c два однакові хибні MI поспіль зіпсували розшифровку");

        /* ---- T4: вхід посередині виклику з PI (як у стокової, що з'єднується пізніше): MI з PI = початковий,
         *      а ефір уже на суперфреймі 5 -> ресинхронізація за 2 суперфрейми ---- */
        make_call(0x2468ACE0u);
        init_run(&r, conv, 1);
        r.startSf = 5;
        /* конвенція вже вивчена в попередньому PI-якірному виклику (див. RXMI_LECUR): вхід посередині сам
         * її вивчити не може -- зсунутий на крок приймач неможливо відрізнити від «іншої конвенції» */
        g_lecur = conv;
        run_rx(&r);
        sf = stable_from(&r);
        printf("  T4 вхід у виклик з суперфрейму 5 при PI-якорі на початковий MI: стабільно з %d\n", sf);
        CHECK(sf <= r.startSf + 3, "T4 пізній вхід з PI не синхронізувався за 3 суперфрейми (стабільно з %d)", sf);
    }
    printf(g_fail ? "=== ПРОВАЛИ: %d ===\n" : "УСЕ ПРОЙДЕНО\n", g_fail);
    return g_fail ? 1 : 0;
}
