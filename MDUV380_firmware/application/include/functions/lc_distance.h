/*
 * R91C (форк): відстань і азимут від власної позиції до позиції кореспондента, прийнятої в GPS-блоці LC 0x08 (decodeGPSPosition(), uiUtilities.c).
 *
 * ENABLE_LC_DISTANCE -- окремий прапорець (типова збірка байт-у-байт стокова). Діє лише разом з APRS-приймачем (APRS_RX, functions/aprs_rx_cfg.h): формат відстані
 * береться з aprsRxFormatGeo() (км і м, без миль), тож окремого форматера нема. Геометрія -- наявні distanceBetweenTwoCoords() і courseTo() (uiUtilities.c).
 *
 * Нових налаштувань, масивів і статиків нема: використовуються лише локальні змінні й наявні поля LinkItem_t.locationLat/locationLon.
 */
#ifndef LC_DISTANCE_H_
#define LC_DISTANCE_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "functions/aprs_rx_cfg.h"
#include "functions/aprs_rx_parse.h"   /* aprsBearingKnown(), APRS_BEARING_MIN_M */
#include "functions/aprs_chevron.h"    /* aprsChevron_t, aprsChevronGeom() */

#if defined(ENABLE_LC_DISTANCE) && defined(APRS_RX)
#define LC_DISTANCE 1

/* Наявні функції прошивки, що їх використовує lc_distance.c (прототипи ті самі, що в user_interface/uiUtilities.h і functions/aprs_rx.h: у uiUtilities.c, який підключає
 * обидва заголовки, будь-яка розбіжність дала б помилку компіляції). Окремо оголошені, щоб файл збирався на хості без заголовків плати. */
double distanceBetweenTwoCoords(double lat1, double lon1, double lat2, double lon2, bool inKm);
double courseTo(double lat1, double lon1, double lat2, double lon2);
void aprsRxFormatGeo(char *buf, size_t size, uint32_t distM, uint16_t bearing);
void aprsRxFormatDist(char *buf, size_t size, uint32_t distM);

/* Розмір буфера підпису (замість Maidenhead): найгірший випадок "20037км NW" (10) + NUL; з запасом. */
#define LC_DIST_LABEL_SIZE   16

/* Чи придатна пара координат: не NaN, |lat| <= 90, |lon| <= 180 і НЕ (0,0). Нуль-нуль -- це розкодований блок з самих нулів (порожній/зіпсований LC), а не
 * реальна позиція: різницю "нема координат" / "(0,0)" в LinkItem_t не зберегти (NaN = нема; GPS-блок із нулів дає рівно 0.0, 0.0), тож (0,0) вважаємо "нема". */
bool lcDistUsable(double lat, double lon);

/* Відстань (м, округлено) і азимут (0..359, градуси від півночі) від (myLat,myLon) до (lat,lon). false -- якщо будь-яка з пар непридатна (lcDistUsable
 * для чужої; діапазон і NaN для своєї). Своя позиція (0,0) допустима: вона задана вручну, а не розкодована. */
bool lcDistCompute(double myLat, double myLon, double lat, double lon, uint32_t *distM, uint16_t *bearingDeg);

/* Підпис "123м NE" / "1.2км NE" / "532км NW" у buf (size >= LC_DIST_LABEL_SIZE). false (buf не чіпаємо) -- своєї позиції нема (ownPositionValid == false) або чужа
 * непридатна. Азимут не показується ближче APRS_BEARING_MIN_M -- те саме правило, що в APRS (aprsRxFormatGeo). */
bool lcDistText(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon);

/* ---- R92: напрямок стрілкою ----------------------------------------------------------------------------------------------------------------------------
 * У шрифті (HX8353E_charset_UA.h: коди 32..254, cp1251) стрілок нема, тож напрям малюється примітивами за геометрією aprsChevronGeom() -- та сама форма, що в екрані APRS, з точним азимутом (не 8 секторів). Літери сторони в тексті більше не друкуються: текст -- лише відстань, напрям -- стрілка. */

/* Підпис "123м" / "1.2км" / "532км" (БЕЗ літер сторони) і азимут. *bearingKnown = (відстань >= APRS_BEARING_MIN_M): ближче азимут не визначений -- стрілку не малювати.
 * Умови false/true ті самі, що в lcDistText(); buf >= LC_DIST_LABEL_SIZE. */
bool lcDistLabel(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon, uint16_t *bearingDeg, bool *bearingKnown);

/* Рядок шапки виклику, де після displayContactTextInfos() опиниться кінець тексту з підписом (textLen = довжина "ім'я [відстань]"): FIRST -- перший рядок, SECOND -- другий,
 * NONE -- підпису не видно. Дзеркалить правила displayContactTextInfos(): рядок >= 5 символів з isFromTalkerAlias; режим "лише один рядок" (singleLineOnly) або "авто"
 * (autoSplit) з текстом <= 16 -- усе в першому рядку (довше 16 при singleLineOnly -- обрізається, підпису не видно); інакше позивний/слово -- у першому, решта з підписом -- у другому. */
typedef enum { LC_ROW_NONE = 0, LC_ROW_FIRST, LC_ROW_SECOND } lcDistRow_t;
lcDistRow_t lcDistLabelRow(size_t textLen, bool singleLineOnly, bool autoSplit);

/* Комірка стрілки: ЗАВЖДИ в правому полі рядка (текст до 16 символів по 8 px = 128 px, по центру => з кожного боку >= 16 px вільно; комірка 147..157). Центр
 * (cx, cy) = (screenW - 8, rowY + rowH/2). З R93 форма -- єдиний «навігаційний наконечник» (aprsChevronGeom(): гострий трикутник з виїмкою ззаду), вісь від центру до вістря
 * LC_ARROW_LEN = 4 px (повна висота 8 px, кутові точки основи на 1.28*4 = 5.1 від центру -- у квадраті 10x10). Малювати двома залитими трикутниками
 * (вістря, ліва, виїмка) і (вістря, права, виїмка). */
#define LC_ARROW_LEN     4
#define LC_ARROW_MARGIN  8
typedef struct
{
	aprsChevron_t g;    /* вістря tx,ty, кутові точки lx,ly / rx,ry і виїмка nx,ny (aprsChevronGeom) */
	int16_t       cx, cy; /* центр комірки */
} lcDistArrow_t;
void lcDistArrowGeom(lcDistArrow_t *a, int16_t screenW, int16_t rowY, int16_t rowH, uint16_t bearingDeg);

#endif /* ENABLE_LC_DISTANCE && APRS_RX */
#endif /* LC_DISTANCE_H_ */
