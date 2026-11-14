/* R98-FIX2 Е: dmrAesRxRetune() -- перенастроювання приймача AES на ІНШИЙ канал (картки A <-> B режиму «Подвійний прийом»).
 * Тест #include-ить СПРАВЖНІЙ dmr_aes_hook.c. Перевіряє: стан RX попереднього каналу (активність розшифровки, ключ останнього виклику,
 * кандидат PI, «відмовлено») скинуто; завантажені ключі, навчена конвенція late entry і TX-стан НЕ зачеплено; ключ ФІЛЬТРА каналу береться
 * з currentChannelData у момент використання (різні слоти A і B -- без жодного кешу). */
#include "../application/source/crypto/dmr_aes_hook.c"

#include <stdio.h>
#include <stdlib.h>

CodeplugChannel_t *currentChannelData = NULL;
bool SPI_Flash_read(uint32_t a, uint8_t *b, int n) { (void)a; memset(b, 0xFF, (size_t)n); return true; }
bool SPI_Flash_write(uint32_t a, uint8_t *b, int n) { (void)a; (void)b; (void)n; return true; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *d, int m) { (void)t; (void)d; (void)m; return false; }
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *d, int l) { (void)t; (void)d; (void)l; return false; }
static uint32_t g_ms = 1000;
uint32_t ticksGetMillis(void) { return g_ms; }
void hrc6000DiagOursLC(uint8_t lc12[12]) { memset(lc12, 0, 12); }

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { g_fail++; printf("  ПРОВАЛ: "); printf(__VA_ARGS__); printf("\n"); } else { printf("  ok   "); printf(__VA_ARGS__); printf("\n"); } } while (0)

int main(void)
{
    printf("test_aes_retune:\n");
    dmrAesInit();
    uint8_t key[32]; memset(key, 0x11, sizeof key);
    dmrAesSetKeyRam(1, key); memset(key, 0x22, sizeof key); dmrAesSetKeyRam(2, key);
    uint16_t maskBefore = dmrAesGetKeyMask();
    int fkBefore = dmr_aes_first_keyid();   /* ключі в RAM-сховищі: перший завантажений -- слот 1 */

    /* стан «після виклику на A» (K1): активна розшифровка, ключ останнього виклику, кандидат PI, відмова */
    s_rxActive = 1; s_rxBurstEnc = 1; s_rxKeyId = 1;
    s_rxPendValid = 1; s_rxPendMi = 0xDEADBEEF; s_rxPendKeyId = 1;
    s_rxDeniedKeyId = 2; s_rxDeniedWhy = 2;
    s_rxMiFlags = RXMI_LECUR | RXMI_PISEEDED;
    s_txActive = 1; s_txKeyId = 1;

    dmrAesRxRetune();

    CHECK(s_rxActive == 0 && s_rxBurstEnc == 0, "розшифровку виклику з A зупинено (виклик без термінатора не «тече» на B)");
    CHECK(s_rxKeyId == 0, "ключ останнього виклику (запасний для late entry) скинуто -- не підставиться на B");
    CHECK(s_rxPendValid == 0 && s_rxPendMi == 0 && s_rxPendKeyId == 0, "кандидат PI з A не підтвердиться на B");
    CHECK(s_rxDeniedKeyId == 0 && s_rxDeniedWhy == 0, "діагностика «відмовлено» скинута");
    CHECK(dmrAesGetKeyMask() == maskBefore && fkBefore == 1 && dmr_aes_first_keyid() == fkBefore, "завантажені ключі не зачеплено (перший слот %d)", dmr_aes_first_keyid());
    CHECK(s_rxMiFlags == (RXMI_LECUR | RXMI_PISEEDED), "навчена конвенція late entry не зачеплена");
    CHECK(s_txActive == 1 && s_txKeyId == 1, "TX-стан не зачеплено");

    /* ключ фільтра -- з currentChannelData у момент використання: A -> слот 1, B -> слот 2, B без шифру (0xFF) */
    CodeplugChannel_t chA, chB, chC;
    memset(&chA, 0, sizeof chA); memset(&chB, 0, sizeof chB); memset(&chC, 0, sizeof chC);
    codeplugChannelSetAesKeySlot(&chA, 1);
    codeplugChannelSetAesKeySlot(&chB, 2);
    codeplugChannelSetAesKeySlot(&chC, 0xFF);
    currentChannelData = &chA; uint8_t fa = rxChannelKeyFilter();
    currentChannelData = &chB; uint8_t fb = rxChannelKeyFilter(); int allowB = rxChannelAllowsAesDetect();
    currentChannelData = &chC; uint8_t fc = rxChannelKeyFilter(); int allowC = rxChannelAllowsAesDetect();
    CHECK(fa == 1 && fb == 2 && allowB, "фільтр іде за каналом: A -> K1, B -> K2 (без кешу)");
    CHECK(fc == 0 && allowC == 0, "канал без шифру (Off): розшифровка не пробується");

    /* повторний виклик нічого не ламає (ідемпотентність) */
    dmrAesRxRetune(); dmrAesRxRetune();
    CHECK(s_rxActive == 0 && s_rxKeyId == 0 && dmrAesGetKeyMask() == maskBefore, "повторні виклики безпечні");

    printf(g_fail ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", g_fail);
    return g_fail ? 1 : 0;
}
