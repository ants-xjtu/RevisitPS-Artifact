/*
 * net.h - Some network related utilities
 */
#ifndef __LIBNETWORK_H__
#define __LIBNETWORK_H__
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <unistd.h>
#include <string.h>

/*
 * Convert a rate (in bps) to a user-friendly string
 * E.g., 1000000bps --> 1Mbps
*/
void bps2user(long bps, char *buf);

/*
 * Convert byte to a user-friendly string
 * E.g., 1024Byte --> 1KiB
*/
void byte2user(long bytes, char *buf);
#endif
