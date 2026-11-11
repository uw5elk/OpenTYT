/* R91C (форк): див. functions/lc_distance.h. Увесь файл -- лише під ENABLE_LC_DISTANCE (+ APRS_RX). */
#include "functions/lc_distance.h"

#if defined(LC_DISTANCE)

#include <math.h>
#include <stdio.h>

bool lcDistUsable(double lat, double lon)
{
	if (isnan(lat) || isnan(lon))
	{
		return false;
	}

	if ((lat < -90.0) || (lat > 90.0) || (lon < -180.0) || (lon > 180.0))
	{
		return false;
	}

	return !((lat == 0.0) && (lon == 0.0));
}

bool lcDistCompute(double myLat, double myLon, double lat, double lon, uint32_t *distM, uint16_t *bearingDeg)
{
	if ((isnan(myLat) || isnan(myLon) || (myLat < -90.0) || (myLat > 90.0) || (myLon < -180.0) || (myLon > 180.0)) || (lcDistUsable(lat, lon) == false))
	{
		return false;
	}

	double m = distanceBetweenTwoCoords(myLat, myLon, lat, lon, false);
	double brg = courseTo(myLat, myLon, lat, lon);

	*distM = (m < 0.0) ? 0U : (uint32_t)(m + 0.5);
	*bearingDeg = (uint16_t)(((int)(brg + 0.5)) % 360);

	return true;
}

bool lcDistText(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon)
{
	uint32_t distM;
	uint16_t brg;

	if ((ownPositionValid == false) || (lcDistCompute(myLat, myLon, lat, lon, &distM, &brg) == false))
	{
		return false;
	}

	aprsRxFormatGeo(buf, size, distM, brg);

	return true;
}

#endif /* LC_DISTANCE */
