/*
 * dmr_sms.h — on-radio encrypted DMR short-message (SMS) service for OpenGD77-AES.
 *
 * Builds on the proven pieces:
 *   - crypto/dmr_aes.c  : AES-256-ECB encrypt/decrypt + dmr_sms_rx_decrypt (RE'd + on-air
 *                         validated 2026-06-27; a stock TYT decrypts our TX).
 *   - functions/dmr_data.c : dmrDataTxLoad() data-burst TX harness (keys a data call).
 *   - hardware/HR-C6000.c  : the RX interrupt hands each BPTC-decoded, CRC-checked data
 *                            burst (page 0x02) to dmrSmsRxBurst() for software reassembly.
 *
 * The whole module is behind ENABLE_AES + ENABLE_DMR_DATA, so stock builds are byte-identical.
 * Message store lives in the OpenGD77 custom-data MESSAGES block (SPI flash) so it survives a
 * power-cycle; a CCM-RAM working copy is the live store (no net-new main RAM -> AMBE codec
 * buffer addresses don't shift). See dmr_sms.c.
 *
 * LEGAL: encrypted traffic is illegal on amateur bands in most jurisdictions. PMR/commercial use.
 */
#ifndef _OPENGD77_DMR_SMS_H_
#define _OPENGD77_DMR_SMS_H_

#include <stdint.h>
#include "functions/aprs_rx_cfg.h"   /* R8: ENABLE_APRS_RX (в т.ч. з ENABLE_APRS_RX_PROBE) */

#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)

#define DMR_SMS_TEXT_MAX    144    /* hard max chars stored/composed per message (buffer size) */
#define DMR_SMS_STORE_DATA  1342   /* packed variable-length message bytes (keeps the MSGS block
                                    * the same 1352 B total as the old fixed 24x56 array) */

/* message record flags */
#define DMR_SMS_FLAG_USED      0x01
#define DMR_SMS_FLAG_UNREAD    0x02
#define DMR_SMS_FLAG_OUTGOING  0x04   /* a Sent message (else Inbox)        */
#define DMR_SMS_FLAG_GROUP     0x08   /* peerId is a talkgroup (else DMR ID) */
#define DMR_SMS_FLAG_FOREIGN   0x10   /* Вхідні: адресоване НЕ нам -- прийнято тільки тому, що
                                       * увімкнено монітор (BIT_SMS_MONITOR_ALL). У списку
                                       * позначається окремо, щоб оператор не сплутав чужий
                                       * наказ зі своїм. */
#define DMR_SMS_FLAG_DELIVERED 0x20   /* Надіслані: отримали link-layer квитанцію (Response DPF=1)
                                       * від адресата на наш CONFIRMED SMS. Записується у теку
                                       * «Надіслані» dmrSmsRxTick()-ом (не ISR). */

#if defined(ENABLE_APRS_RX)
#define DMR_SMS_FLAG_APRS      0x40   /* R8: вхідне -- повідомлення APRS (прийнято з ефіру AFSK 1200, а не DMR).
                                       * Вільний біт прапорців запису v3; довжина записів і блоків не змінена.
                                       * peerId = 0, відправник -- префікс тексту «CALL: ». */
#endif

typedef struct
{
	uint8_t  flags;
	uint8_t  textLen;
	uint16_t seq;                 /* monotonically increasing -> newest = highest seq */
	uint32_t peerId;              /* inbox: source ID; sent: destination ID/TG         */
	char     text[DMR_SMS_TEXT_MAX];
} dmrSmsMessage_t;

/* ---- lifecycle --------------------------------------------------------- */
/* Load the message store from flash into the CCM working copy. Call once at boot. */
void dmrSmsInit(void);
/* R12: лише скинути RAM-стан (без читання флеша) -- викликається з applicationMain.c одразу після HRC6000Init(), ДО
 * dmrSmsInit(): CCM при старті сміття, а HR-C6000 ISR уже може віддати data-burst у dmrSmsRxBurst(). */
void dmrSmsRuntimeInit(void);
/* Лише перечитати сховище й MSGC-конфіг (вхід у меню «Повідомлення»). НЕ скидає стан
 * прийому, відкладену квитанцію, N(S) і лічильники -- на відміну від dmrSmsInit(). */
void dmrSmsReloadStore(void);

/* ---- store query (UI) -------------------------------------------------- */
/* Count of messages for a folder: outgoing!=0 -> Sent, ==0 -> Inbox. */
int  dmrSmsCount(int outgoing);
/* idx 0 = newest. Returns NULL if out of range. */
const dmrSmsMessage_t *dmrSmsGet(int outgoing, int idx);
/* Total unread (Inbox) messages — for the idle-screen indicator. */
int  dmrSmsUnreadCount(void);
/* ui6: час запису (секунди UTC; 0 = невідомо / годинник не був виставлений). Читається прямо
 * зі сховища (запис v3), у dmrSmsMessage_t поля немає -- RAM не росте. */
uint32_t dmrSmsGetTime(int outgoing, int idx);
/* ui6: найновіше вхідне для банера (відкладене, ще не у флеші, або перше у «Вхідних») і його час.
 * Повертає той самий буфер, що й dmrSmsGet(); NULL -- вхідних немає. */
const dmrSmsMessage_t *dmrSmsNewestInbox(uint32_t *timeOut);
/* ui6: адресат (DMR ID або TG) останнього прийнятого SMS -- банер «ВІД -> КОМУ» для монітора. */
uint32_t dmrSmsLastRxDst(void);

#if defined(ENABLE_APRS_RX)
/* R8: покласти в «Вхідні» повідомлення APRS (text -- cp1251, вже з префіксом «ВІДПРАВНИК: »). Блокуючий
 * запис у флеш (як у решти SMS) -- викликати з головної задачі, не з переривання і не під час передачі. */
void dmrSmsAddAprsInbox(const char *text, int len);
#endif

/* ---- store mutate (UI) ------------------------------------------------- */
void dmrSmsMarkRead(int outgoing, int idx);
void dmrSmsMarkAllRead(void);
void dmrSmsDelete(int outgoing, int idx);
void dmrSmsDeleteAll(int outgoing);     /* outgoing<0 -> both folders */

/* ---- RX (HR-C6000 ISR context) ----------------------------------------- *
 * Called for each CRC-valid data-sync burst: rxDataType is the ETSI slot data type
 * (6 = Data Header, 7 = Rate-1/2 Data), payload12 = the 12 BPTC-decoded info bytes
 * read from HR-C6000 page 0x02. Accumulates a PDU; on completion raises a flag the
 * main loop drains in dmrSmsRxTick(). Cheap + ISR-safe (no flash, no AES here). */
void dmrSmsRxBurst(int rxDataType, const uint8_t *payload12);
/* Drop any partial RX accumulation (call on Terminator / call end). */
void dmrSmsRxReset(void);

/* dmrSmsRxDiagBurst() HR-C6000 кличе на КОЖЕН data-sync burst (будь-який тип/CRC). У будь-якій
 * збірці ставить мітку «канал зайнятий» (гейт тиші квитанції); лічильники -- ENABLE_SMS_DIAG. */
void dmrSmsRxDiagBurst(int rxDataType, int crcOk);

#if defined(ENABLE_SMS_DIAG)
/* ENABLE_SMS_DIAG (cleanup1, 2026-10-05): уся діагностика SMS -- для розборів, не для щоденної
 * збірки. Diagnostic (bench bring-up). dmrSmsRxDiag() fills out[7]:
 *   [0]=all data bursts, [1]=hdr CRC-ok, [2]=hdr CRC-bad, [3]=blk CRC-ok,
 *   [4]=blk CRC-bad, [5]=PDUs reassembled, [6]=messages decoded. */
void dmrSmsRxDiag(uint32_t out[7]);
void dmrSmsRxDiagTypes(uint32_t out[16]);   /* гістограма rxDataType (0..15) усіх data-sync бурстів */
/* Діагностика link-layer квитанції на вхідне CONFIRMED SMS -- де саме рветься ланцюг:
 *   [0]=заголовків CONFIRMED, [1]=в чергу, [2]=в ефір, [3]=кинуто (канал не звільнився),
 *   [4]=p[0] ост. вхідного data-заголовка, [5]=p[1], [6]=груповий?, [7]=адресоване нам?,
 *   [8]=ревізія формату квитанції (яка прошивка залита), [9]=повторів у черзі,
 *   [10]=виміряна пауза до віддачі квитанції, мс (еталон стокової ~80),
 *   [11]=цільова пауза (підбірна), [12]=CSBK-преамбул перед квитанцією. */
void dmrSmsAckDiag(uint32_t out[13]);
/* Підбір подачі квитанції без перепрошивки (USB 0xB2): скільки разів повторити заголовок
 * (1..6), через скільки мс після тиші в каналі віддати і скільки CSBK-преамбул поставити
 * попереду (0..16). Типово 1 / 80 / 6 -- преамбули як у нашого SMS, яке стокова приймає. */
void dmrSmsAckSetTuning(uint8_t repeats, uint16_t delayMs, uint8_t preambles);
void dmrSmsRxDiagReset(void);
/* Dump the last reassembled (still-encrypted) PDU + metadata for offline analysis:
 * out = [pduLen_hi, pduLen_lo, keyId, expBlocks, peer(4 LE), rawPdu...]. Returns length. */
int  dmrSmsRxLastPdu(uint8_t *out, int maxlen);
/* Дамп СИРИХ блоків навантаження разом зі службовими байтами (DBSN+CRC9), як їх віддав чип:
 * out = [count, (len, bytes...) x count]. Еталон для реверсу CRC9 -- без нього не зібрати
 * власні CONFIRMED-блоки. Скидається разом з рештою лічильників (0x94). */
int  dmrSmsRxRawBlocks(uint8_t *out, int maxlen);
#endif /* ENABLE_SMS_DIAG */

/* ---- RX (main-loop context) -------------------------------------------- *
 * Decrypt a completed PDU, store it to the Inbox, and pop a notification. Safe to
 * call every main-loop tick; does nothing unless a PDU has been reassembled. */
void dmrSmsRxTick(void);

/* ---- config (quick-text presets + default recipient) ------------------- *
 * Read from the MSGC custom-data block written by the CHIRP module. */
#define DMR_SMS_NUM_PRESETS  10
int  dmrSmsPresetCount(void);              /* number of non-empty presets */
const char *dmrSmsPresetGet(int idx);      /* preset text by index, or NULL */
/* Default compose recipient; *dst==0 if unset (fall back to current channel). */
void dmrSmsDefaultRecipient(uint32_t *dst, int *group);
/* CHIRP-configurable max compose length, clamped to [1, DMR_SMS_TEXT_MAX]; the MSGC
 * maxLen byte (0 or out-of-range -> DMR_SMS_TEXT_MAX). Limits on-radio composing only. */
int  dmrSmsMaxLen(void);
/* CHIRP "Encrypt SMS" master gate: 1 = encrypt per-channel like voice, 0 = always cleartext.
 * Default (unset MSGC byte) = 1, preserving the encrypted behaviour. */
int  dmrSmsEncryptEnabled(void);

/* ---- TX ---------------------------------------------------------------- *
 * Build a stock-TYT-compatible SMS and key a data call. Encrypted (AES-256-ECB + ENC header)
 * or cleartext per the CHIRP master gate and the channel's encrypt byte (voice logic).
 *   text  : ASCII message (encoded UTF-16LE on the wire)
 *   dst   : destination talkgroup (group!=0) or DMR ID (group==0)
 *   keyId : explicit AES key slot 1..15 (0 -> follow the gate + per-channel voice logic)
 * Returns 0 on success, <0 on error (busy / bad args). Also files the message into Sent. */
int  dmrSmsSend(const char *text, uint32_t dst, int group, uint8_t keyId);

#if defined(ENABLE_SMS_DIAG)
/* DIAGNOSTIC (USB 0x97 A/B): make the next dmrSmsSend calls skip the store_add() Sent-folder
 * flash write, to isolate bug #3 (menu sends after the first fail; USB harness sends don't).
 * The menu path never sets this; it is toggled only around the 0x97 handler call. */
void dmrSmsDiagSetSkipStore(int skip);
#endif

/* One-shot: повертає 1 якщо отримали Response-header (link-layer ACK, DPF=1) від адресата
 * нашого останнього CONFIRMED SMS, і скидає прапорець. 0 -- ще не отримали або нічого
 * не відправляли. Безпечно викликати з основного циклу кожен тік. */
int dmrSmsTxAcked(void);

/* ---- Режим TX SMS (Task #31) ------------------------------------------- *
 * 0 = Без підтвердження (ТИПОВО): рівно шлях 438ec23, що працював у полі -- Unconfirmed,
 *     сирі 12-байтні rate-1/2 блоки (dmrSmsPduBuildUnconf, functions/dmr_sms_pdu.c)
 * 1 = Підтв. rate-1/2 (CONFIRMED, rate-1/2 блоки з DBSN+CRC9)
 * 2 = Підтв. rate-3/4 (CONFIRMED, rate-3/4 блоки -- так шле стокова TYT)
 * Зберігається у CODEPLUG_CUSTOM_DATA_TYPE_SMS_TX_MODE (1 байт, SPI flash). */
int  dmrSmsTxMode(void);
void dmrSmsTxModeSet(uint8_t mode);

/* ---- Прийом data-заголовка (HR-C6000 ISR) ------------------------------ *
 * Чи пускати data-заголовок (тип 6) далі у dmrSmsRxBurst/dmrRctlRxBurst: апаратний CRC ok,
 * АБО програмно CRC16 ^ 0xCCCC сходиться. З ENABLE_SMS_DIAG рахує обидва випадки. */
int  dmrSmsRxHdrAccept(int hwCrcOk, const uint8_t *p12);

#if defined(ENABLE_SMS_DIAG)
/* ---- Екран «Діагностика» (меню Повідомлення) --------------------------- *
 * Лише з ENABLE_SMS_DIAG (ui2: у звичайній збірці пункту «Діагностика» немає). */
typedef struct
{
	/* будь-яка збірка: CONFIRMED-заголовків із проханням квитанції / квитанцій у черзі;
	 * PDU з валідним CRC32 / зібрано під заголовок, а CRC32 не зійшовся; корекція трибітів
	 * (fix7) -- виправлено / кілька кандидатів / жодного */
	uint16_t ackSeen, ackQueued;
	uint16_t pduOk, crcFail;
	uint16_t fixOk, fixAmb, fixNone;
#if defined(ENABLE_SMS_DIAG)
	/* Квитанція на ВХІДНЕ CONFIRMED (ми квитуємо) */
	uint16_t ackSent, ackStale, ackDelayMs;
	/* dmr_data.c: черга відхилена (передача активна) / перший burst пішов у чип /
	 * вихід по таймауту / таймаут без жодного burst-а */
	uint16_t dataRejected, dataStarted, dataTimeout, dataNoStart;
	/* Наше CONFIRMED (нас квитують) */
	uint16_t txConf, respAll, respForUs, respMatch;
	/* data-заголовки (тип 6): HW CRC ok / HW bad але SW ok / відкинуто */
	uint16_t hdrHwOk, hdrSwOk, hdrBad;
	/* fix3, сторінка 2: data-переривань типу 6 / 8 до фільтрів; скільки з них відкинув би
	 * фільтр RX-стану HR-C6000; фактична затримка квитанції від тиші до старту TX, мс */
	uint16_t isr6, isr8, filt6, filt8, ackRealMs;
	/* ui1/fix4: етапи «Квит факт», мс: тиша->черга, черга->ключування, ключування->старт
	 * TX_START_1, старт->перший burst квитанції в чипі */
	uint16_t stgQ, stgK, stgS, stgB;
	/* diag5, сторінка 3: блок без заголовка / блок відкинуто (попередній PDU не забрано) /
	 * переповнення / зайві блоки / головний цикл: не нам / зіпсований; найбільша затримка
	 * «готовий -> забрано», мс */
	uint16_t blkNoHdr, blkBusy, blkOvf, blkExtra, tickNotUs, tickBad, pickMaxMs;
	/* diag6, сторінка 4: блоків rate-3/4 CONFIRMED з DBSN != порядковий номер (повтор або
	 * перестановка); блоків т8, які HW позначив CRC-валідними */
	uint16_t dbsnBad, hw8Ok;
	/* fix7, сторінка 3: час останньої і найдовшої корекції, мс */
	uint16_t fixLastMs, fixMaxMs;
#endif
} dmrSmsDiagScreen_t;
void dmrSmsDiagScreenGet(dmrSmsDiagScreen_t *d);
void dmrSmsDiagScreenReset(void);
#endif

#if defined(ENABLE_SMS_DIAG)
/* diag6: знімок ОСТАННЬОГО повністю зібраного PDU з невалідним CRC32 («CRC пог»). */
typedef struct
{
	uint8_t        n;        /* блоків у знімку (0 = знімка ще нема), до 8 */
	uint8_t        len;      /* байтів у блоці: 18 (rate-3/4, зі службовими DBSN+CRC9) або 12 */
	uint8_t        hwOk;     /* біт i = чип позначив блок i CRC-валідним */
	uint16_t       seq;      /* номер цього «CRC пог» від скидання */
	uint32_t       crcWant;  /* CRC32 з останніх 4 байтів PDU */
	uint32_t       crcGot;   /* CRC32, порахований по прийнятому */
	const uint8_t *hdr;      /* сирий заголовок (12 Б) */
} dmrSmsBadSnapInfo_t;
int            dmrSmsBadSnapInfo(dmrSmsBadSnapInfo_t *i);
/* Сирий блок idx знімка (len байтів) і його час від заголовка, мс; NULL -- нема такого. */
const uint8_t *dmrSmsBadSnapBlock(int idx, uint16_t *ms);
/* Експеримент: наше CONFIRMED без термінатора (dmrDataTxLoadFast). Не зберігається. */
int  dmrSmsDiagFastEnd(void);
void dmrSmsDiagFastEndToggle(void);
/* fix3: перемикачі 2-ї сторінки «Діагностики» (не зберігаються, типові -- DMR_SMS_DEFAULT_*). */
int  dmrSmsRxBypass(void);              /* RX обхід фільтра RX-стану для data 6/7/8 (ISR) */
void dmrSmsDiagRxBypassToggle(void);
int  dmrSmsDiagAckTerm(void);           /* 1 = квитанція з термінатором */
void dmrSmsDiagAckTermToggle(void);
int  dmrSmsDiagAckPreambles(void);      /* CSBK-преамбул перед квитанцією (0 або 6) */
void dmrSmsDiagAckPreamblesToggle(void);
int  dmrSmsDiagAckPause(void);          /* цільова пауза квитанції, мс (20/50/80) */
void dmrSmsDiagAckPauseToggle(void);
/* ISR HR-C6000: облік data-переривання (тип 6/8) до фільтрів; filterDrops -- чи відкинув би
 * його фільтр RX-стану. */
void dmrSmsRxEarlyNote(int rxDataType, int filterDrops);
#else
/* cleanup1: «RX обхід» перевірено на залізі (2026-10-05) -- завжди увімк
 * (= DMR_SMS_DEFAULT_RX_BYPASS у dmr_sms_pdu.h). */
#define dmrSmsRxBypass() (1)
#endif /* ENABLE_SMS_DIAG */

#endif /* ENABLE_DMR_DATA && ENABLE_AES */
#endif /* _OPENGD77_DMR_SMS_H_ */
