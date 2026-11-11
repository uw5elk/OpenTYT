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

#if defined(ENABLE_LC_DISTANCE) && defined(APRS_RX)
#define LC_DISTANCE 1

/* Наявні функції прошивки, що їх використовує lc_distance.c (прототипи ті самі, що в user_interface/uiUtilities.h і functions/aprs_rx.h: у uiUtilities.c, який підключає
 * обидва заголовки, будь-яка розбіжність дала б помилку компіляції). Окремо оголошені, щоб файл збирався на хості без заголовків плати. */
double distanceBetweenTwoCoords(double lat1, double lon1, double lat2, double lon2, bool inKm);
double courseTo(double lat1, double lon1, double lat2, double lon2);
void aprsRxFormatGeo(char *buf, size_t size, uint32_t distM, uint16_t bearing);

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

#endif /* ENABLE_LC_DISTANCE && APRS_RX */
#endif /* LC_DISTANCE_H_ */
