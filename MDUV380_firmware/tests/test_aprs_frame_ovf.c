/*
 * test_aprs_frame_ovf.c -- гілка «кадр завеликий» (R10-fix2): той самий тест, що test_aprs_frame.c, але aprs.c збирається з
 * МАЛИМ буфером кадру (40 байт) -- у справжньому буфері (256 байт) кадр режиму гарантовано влазить (_Static_assert у aprs.c),
 * тож дістатися відмови інакше не можна.
 */
#define AX25_PACKET_BUFFER_SIZE 40U
#define APRS_FRAME_TEST_SMALL_BUFFER 1
#include "test_aprs_frame.c"
