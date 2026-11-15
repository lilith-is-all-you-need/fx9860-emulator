#include "compat.h"
#include <stdio.h>
FILE *probe_utf8_fopen(const char *path, const char *mode);
#define fopen probe_utf8_fopen
