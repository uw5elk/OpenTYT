/*
 * menuVolumeProbe.h -- R77A: екран «Гучн. проба». Не окреме меню (нового ID меню нема), а режим усередині «Опцій рації»: menuRadioOptions.c
 * передає сюди тіки й події, поки volumeProbeIsOn().
 */
#ifndef _OPENGD77_MENU_VOLUME_PROBE_H_
#define _OPENGD77_MENU_VOLUME_PROBE_H_

#include "functions/volume_probe.h"

#if defined(VOLUME_PROBE)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

void menuVolumeProbeEnter(void);
/* Кожен тік «Опцій рації», поки проба відкрита. false -- вийшли (проба закрита, треба перемалювати список). */
bool menuVolumeProbeTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_VOLUME_PROBE_H_ */
