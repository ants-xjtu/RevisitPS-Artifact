#include "convert.h"

/*
 * Convert a rate (in bps) to a user-friendly string
 * E.g., 1000000bps --> 1Mbps
*/
void bps2user(long bps, char *buf) {
    if (bps >= 1000000000L)
        sprintf(buf, "%.3lfGbps", (bps/1000.0/1000.0/1000.0));
    else if (bps >= 1000000)
        sprintf(buf, "%.3lfMbps", (bps/1000.0/1000.0));
    else if (bps >= 1000)
        sprintf(buf, "%.3lfKbps", (bps/1000.0));
    else
        sprintf(buf, "%ldbps", bps);
}

void byte2user(long bytes, char *buf) {
    if (bytes >= (1<<30))
        sprintf(buf, "%.3lfGiB", 1.0*bytes/(1<<30));
    else if (bytes >= (1<<20))
        sprintf(buf, "%.3lfMiB", 1.0*bytes/(1<<20));
    else if (bytes >= (1<<10))
        sprintf(buf, "%.3lfKiB", 1.0*bytes/(1<<10));
    else
        sprintf(buf, "%ldB", bytes);
}
