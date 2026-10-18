/* AES-fix3 C1/C2: сирі LC/EMB у діагностичному дампі (0x84) і блок «наші байти».
 *
 * Тест #include-ить СПРАВЖНІЙ application/source/crypto/dmr_aes_hook.c з -DDMR_AES_DIAG_RX і перевіряє:
 *  - розкладку другого хвоста (магія 0xF3, розміри записів, довжина блоку), старий хвіст (out[3]==66) не зачеплено;
 *  - дедуп сирих LC проти ВСІХ записів кільця (повтор -> hits++, нових записів нема), обгортання кільця на 8;
 *  - EMB-кільце: дедуп і порядок;
 *  - «наші» байти: PI == dmr_pi_build, EMB == dmr_emb_sb_build, Voice LC -- те, що поверне hrc6000DiagOursLC (заглушка тут;
 *    справжня -- клон у HR-C6000.c, його вміст перевіряє syntax_check + огляд), вибір ключа TX-вибір > останній RX > 1;
 *  - dmrAesResetRxDiag чистить усе.
 * Без -DDMR_AES_DIAG_RX тест нічого не перевіряє (збірка без діагностики не має цього коду). */
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
static const uint8_t OURS_LC[12] = { 0x00, 0x10, 0x40, 0x00, 0x00, 0x09, 0x30, 0x0D, 0x40, 0x00, 0x00, 0x00 };
void hrc6000DiagOursLC(uint8_t lc12[12]) { memcpy(lc12, OURS_LC, 12); }

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { g_fail++; printf("  ПРОВАЛ: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint8_t D[4096];
#define OLD_TRL 66
#define F3 (32 + 24 * 16 + OLD_TRL)   /* зсув другого хвоста */

static void mklc(uint8_t *lc, uint8_t tag) { for (int i = 0; i < 12; i++) { lc[i] = (uint8_t)(tag * 37 + i); } }
static int dump(void) { memset(D, 0xEE, sizeof D); return dmrAesGetRxDiag(D, (int)sizeof D); }

int main(void)
{
    uint8_t lc[12], e[4];
    dmrAesInit();
    dmrAesResetRxDiag();

    /* 1. порожній дамп: розкладка */
    int n = dump();
    CHECK(n == F3 + DIAG3_LEN, "довжина дампу %d, очікувано %d", n, F3 + DIAG3_LEN);
    CHECK(D[0] == 0xA5 && D[1] == 24 && D[2] == 16, "старий заголовок");
    CHECK(D[3] == OLD_TRL, "out[3] (старий хвіст) = %d, має лишитись %d", D[3], OLD_TRL);
    CHECK(D[F3] == 0xF3 && D[F3 + 1] == RLC_N && D[F3 + 2] == 20 && D[F3 + 3] == EMBR_N && D[F3 + 4] == 8, "заголовок fix3");
    CHECK((D[F3 + 5] | (D[F3 + 6] << 8)) == DIAG3_LEN, "довжина блоку fix3");
    CHECK(D[F3 + 7] == 0 && D[F3 + 8] == 0, "кільця порожні після reset");
    /* буфер USB: 1536 - 3; дамп мусить у нього влізти */
    CHECK(n <= 512 * 3 - 3, "дамп %d не влазить у COM_BUFFER_SIZE-3", n);
    CHECK(dmrAesGetRxDiag(D, n - 1) == 0, "малий буфер -> 0");

    /* 2. сирі LC: новий, інший, повтор першого */
    dmrAesDiagRawCtx(1, 2, 0); mklc(lc, 1); g_ms = 1100; dmrAesDiagRawLC(lc);
    dmrAesDiagRawCtx(1, 2, 1); mklc(lc, 2); g_ms = 1200; dmrAesDiagRawLC(lc);
    dmrAesDiagRawCtx(3, 1, 0); mklc(lc, 1); g_ms = 1300; dmrAesDiagRawLC(lc);   /* повтор LC №1 */
    n = dump();
    uint8_t *f = D + F3;
    CHECK(f[7] == 2, "записів LC %d, очікувано 2 (повтор не вноситься)", f[7]);
    CHECK((f[9] | (f[10] << 8)) == 3 && (f[11] | (f[12] << 8)) == 1, "лічильники: усього %d, повторів %d", f[9] | (f[10] << 8), f[11] | (f[12] << 8));
    {
        uint8_t *r0 = f + 48;
        mklc(lc, 1);
        CHECK(memcmp(r0 + 8, lc, 12) == 0, "байти LC0");
        CHECK(r0[0] == 1 && (r0[1] & 3) == 2 && ((r0[1] >> 2) & 1) == 0 && (r0[1] & 8), "контекст LC0: dt=%d fl=%02X", r0[0], r0[1]);
        CHECK(r0[2] == 1, "hits LC0 = %d, очікувано 1", r0[2]);
        CHECK((r0[4] | (r0[5] << 8)) == 1100 && (r0[6] | (r0[7] << 8)) == 1300, "ts першої появи / останнього повтору");
        uint8_t *r1 = f + 48 + 20;
        CHECK(((r1[1] >> 2) & 1) == 1 && r1[0] == 1, "контекст LC1 (PI=1)");
    }

    /* 3. обгортання: ще 8 відмінних LC -> у кільці (RLC_N) лишаються останні, LC №1 і №2 витіснено */
    for (uint8_t t = 10; t < 18; t++) { dmrAesDiagRawCtx(1, 2, 0); mklc(lc, t); dmrAesDiagRawLC(lc); }
    n = dump(); f = D + F3;
    CHECK(f[7] == 10, "вільнобіжний індекс %d, очікувано 10", f[7]);
    {
        int found1 = 0, found17 = 0;
        for (int i = 0; i < RLC_N; i++)
        {
            uint8_t *r = f + 48 + i * 20;
            mklc(lc, 1);  if (memcmp(r + 8, lc, 12) == 0) { found1 = 1; }
            mklc(lc, 17); if (memcmp(r + 8, lc, 12) == 0) { found17 = 1; }
        }
        CHECK(!found1 && found17, "обгортання: старий LC витіснено (%d), найновіший є (%d)", found1, found17);
    }

    /* 4. EMB: нове, повтор, інше */
    dmrAesDiagRawCtx(6, 1, 0);
    e[0] = 0x44; e[1] = 0x42; e[2] = 0x88; e[3] = 0x81; g_ms = 2000; dmrAesDiagEmb(e);
    g_ms = 2060; dmrAesDiagEmb(e);
    dmrAesDiagRawCtx(0, 0, 0);
    e[0] = 0; e[1] = 0; e[2] = 0; e[3] = 0; g_ms = 2100; dmrAesDiagEmb(e);
    n = dump(); f = D + F3;
    CHECK(f[8] == 2, "записів EMB %d, очікувано 2", f[8]);
    CHECK((f[13] | (f[14] << 8)) == 3 && (f[15] | (f[16] << 8)) == 1, "EMB: читань %d, повторів %d", f[13] | (f[14] << 8), f[15] | (f[16] << 8));
    {
        uint8_t *q = f + 48 + RLC_N * 20;
        CHECK(q[0] == 6 && (q[1] & 3) == 1 && (q[2] | (q[3] << 8)) == 2000, "EMB0 контекст");
        CHECK(q[4] == 0x44 && q[5] == 0x42 && q[6] == 0x88 && q[7] == 0x81, "EMB0 байти");
        CHECK(q[8] == 0 && (q[9] & 3) == 0 && q[12] == 0 && q[15] == 0, "EMB1 = нулі (чип нічого не віддає -- теж результат)");
    }

    /* 5. «наші» байти: ключ за замовчуванням 1; потім останній RX-ключ; потім TX-вибір */
    uint8_t pi[7], emb[4];
    f = D + F3;
    CHECK(f[17] == 1 && f[18] == 3 && f[19] == 1, "ключ за замовчуванням: key=%d src=%d", f[17], f[18]);
    dmr_pi_build(DMR_ALG_AES256, 1, 0x11223344u, pi);
    dmr_emb_sb_build(1, 5, emb);
    CHECK(memcmp(f + 24, pi, 7) == 0, "PI не збігається з dmr_pi_build");
    CHECK(memcmp(f + 43, emb, 4) == 0, "EMB SB не збігається з dmr_emb_sb_build");
    CHECK(memcmp(f + 31, OURS_LC, 12) == 0, "Voice LC не збігається з hrc6000DiagOursLC");
    CHECK((f[20] | (f[21] << 8) | (f[22] << 16) | ((uint32_t)f[23] << 24)) == 0x11223344u, "MI");
    CHECK(pi[0] == 0x25 && pi[1] == 0x10 && pi[2] == 1 && pi[3] == 0x11 && pi[6] == 0x44, "PI = 25 10 01 <MI4>");
    CHECK(emb[0] == 0x44 && emb[1] == 0x42 && emb[2] == 0x88 && emb[3] == 0x81, "EMB для ключа 1 / AES256 = 44 42 88 81 (відоме значення з документації fork-а)");

    s_rxKeyId = 7; n = dump(); f = D + F3;
    dmr_pi_build(DMR_ALG_AES256, 7, 0x11223344u, pi); dmr_emb_sb_build(7, 5, emb);
    CHECK(f[17] == 7 && f[18] == 2 && memcmp(f + 24, pi, 7) == 0 && memcmp(f + 43, emb, 4) == 0, "останній RX-ключ");
    s_txKeyId = 3; n = dump(); f = D + F3;
    dmr_pi_build(DMR_ALG_AES256, 3, 0x11223344u, pi); dmr_emb_sb_build(3, 5, emb);
    CHECK(f[17] == 3 && f[18] == 1 && memcmp(f + 24, pi, 7) == 0 && memcmp(f + 43, emb, 4) == 0, "TX-вибір ключа важливіший");

    /* 6. «наші» байти не мають побічних ефектів на TX-стан */
    CHECK(s_txActive == 0, "дамп не мусить вмикати шифровану TX");

    /* 7. reset */
    dmrAesResetRxDiag(); n = dump(); f = D + F3;
    CHECK(f[7] == 0 && f[8] == 0 && f[9] == 0 && f[13] == 0, "reset чистить кільця й лічильники");
    for (int i = 0; i < RLC_N * 20 + EMBR_N * 8; i++) { if (f[48 + i] != 0) { CHECK(0, "reset: байт кільця %d не нульовий", i); break; } }

    /* 8. AES-fix4 D1: захоплення CAP_BURSTS burst-ів поспіль (AES-fix5: 24 = чотири суперфрейми), не залежить від s_rxActive */
    {
        uint8_t cap[1024], blk[27];
        dmrAesResetRxDiag();
        CHECK(s_rxActive == 0, "захоплення мусить працювати без активної розшифровки");
        for (int i = 0; i < 27; i++) { blk[i] = 0; }
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(n == 4 + CAP_BURSTS + CAP_BURSTS * 27 && CAP_BURSTS == 24, "довжина дампу захоплення %d", n);
        CHECK(cap[0] == 0 && cap[1] == 0 && cap[2] == CAP_BURSTS && cap[3] == 0, "порожнє захоплення");
        CHECK(n <= 512 * 3 - 3, "дамп захоплення %d не влазить у COM_BUFFER_SIZE-3", n);
        CHECK(dmrAesGetCapData(cap, n - 1) == 0, "малий буфер -> 0");
        /* без озброєння burst-и не пишуться */
        blk[0] = 0x55; dmrAesRxLateEntry(1, blk); n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 0 && cap[1] == 0, "без arm нічого не пишеться");
        /* озброєно посеред суперфрейму: seq 3,4,5 ігноруються, старт на seq 1 */
        dmrAesDiagCapArm();
        for (int q = 3; q <= 6; q++) { blk[0] = (uint8_t)q; dmrAesRxLateEntry(q, blk); }
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 1 && cap[1] == 0 && cap[3] == 0, "чекає seq 1 (state=%d N=%d restarts=%d)", cap[0], cap[1], cap[3]);
        for (int k = 0; k < CAP_BURSTS; k++) { int q = k % 6 + 1; memset(blk, 0, 27); blk[0] = (uint8_t)(0xA0 + k); blk[26] = (uint8_t)q; dmrAesRxLateEntry(q, blk); }
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 3 && cap[1] == CAP_BURSTS && cap[3] == 0, "готово (state=%d N=%d restarts=%d)", cap[0], cap[1], cap[3]);
        {
            int okseq = 1, okdat = 1;
            for (int k = 0; k < CAP_BURSTS; k++)
            {
                okseq &= (cap[4 + k] == (k % 6 + 1));
                okdat &= (cap[4 + CAP_BURSTS + k * 27] == (uint8_t)(0xA0 + k)) && (cap[4 + CAP_BURSTS + k * 27 + 26] == (k % 6 + 1));
            }
            CHECK(okseq, "seq у дампі 1..6,1..6");
            CHECK(okdat, "27 байтів кожного burst збережено без змін і по порядку");
        }
        /* після «готово» нові burst-и стан не чіпають */
        memset(blk, 0xEE, 27); dmrAesRxLateEntry(1, blk);
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 3 && cap[1] == CAP_BURSTS && cap[4 + CAP_BURSTS] == 0xA0, "готове захоплення не перезаписується");
        /* розрив: 1,2,3 -> 5 (втрачено 4) -> скидання, потім чисті 12 */
        dmrAesDiagCapArm();
        blk[0] = 1; dmrAesRxLateEntry(1, blk); dmrAesRxLateEntry(2, blk); dmrAesRxLateEntry(3, blk); dmrAesRxLateEntry(5, blk);
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 1 && cap[1] == 0 && cap[3] == 1, "розрив: скидання (state=%d N=%d restarts=%d)", cap[0], cap[1], cap[3]);
        /* розрив, де новий burst сам seq 1: одразу починає заново */
        dmrAesRxLateEntry(1, blk); dmrAesRxLateEntry(2, blk); dmrAesRxLateEntry(1, blk);
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 2 && cap[1] == 1 && cap[3] == 2, "розрив із seq 1: N=%d restarts=%d", cap[1], cap[3]);
        for (int k = 1; k < CAP_BURSTS; k++) { dmrAesRxLateEntry(k % 6 + 1, blk); }
        n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 3 && cap[1] == CAP_BURSTS && cap[3] == 2, "після розривів готово (state=%d N=%d restarts=%d)", cap[0], cap[1], cap[3]);
        dmrAesResetRxDiag(); n = dmrAesGetCapData(cap, (int)sizeof cap);
        CHECK(cap[0] == 0 && cap[1] == 0 && cap[3] == 0 && cap[4 + CAP_BURSTS] == 0, "reset чистить захоплення");
    }

    printf(g_fail ? "ПРОВАЛ (%d)\n" : "ok\n", g_fail);
    return g_fail ? 1 : 0;
}
#endif
