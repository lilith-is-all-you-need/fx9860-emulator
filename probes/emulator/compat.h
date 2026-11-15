#ifndef PROBE_WIN_COMPAT_H
#define PROBE_WIN_COMPAT_H
#ifdef _WIN32
#include <direct.h>
#include <sys/stat.h>
#include <time.h>
/* MinGW's mkdir takes no POSIX mode. Force-include after CRT declarations. */
#define mkdir(path, mode) _mkdir(path)
static inline struct tm *probe_localtime_r(const time_t *t, struct tm *out)
{
    return localtime_s(out, t) == 0 ? out : NULL;
}
#define localtime_r probe_localtime_r
#endif
#endif
