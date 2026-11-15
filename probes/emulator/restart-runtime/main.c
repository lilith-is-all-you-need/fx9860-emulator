#include <gint/display.h>
#include <gint/gint.h>

volatile int initialized_value = 42;
volatile int zero_value;

int main(void)
{
    gint_setrestart(1);
    initialized_value = 99;
    zero_value = 100;
    dclear(C_WHITE);
    dtext(1, 1, C_BLACK, "RESTART TEST");
    dtext(1, 15, C_BLACK, "RETURN -> MAIN");
    dupdate();
    return 0;
}
