#include "sim.h"
#include <stdio.h>

void test_parser(void);
void test_crc(void);
void test_tmc(void);
void test_planner(void);
void test_arc(void);
void test_laser(void);
void test_endstops(void);
void test_estop(void);
void test_update(void);
void test_commands(void);

int main(void)
{
    static const struct {
        const char *name;
        void (*fn)(void);
    } groups[] = {
        {"parser", test_parser},     {"crc", test_crc},         {"tmc", test_tmc},
        {"planner", test_planner},   {"arc", test_arc},         {"laser", test_laser},
        {"endstops", test_endstops}, {"estop", test_estop},     {"update", test_update},
        {"commands", test_commands},
    };
    for (size_t i = 0; i < sizeof groups / sizeof groups[0]; i++) {
        int before_c = t_checks, before_f = t_failed;
        groups[i].fn();
        printf("%-10s %5d checks, %d failed\n", groups[i].name, t_checks - before_c,
               t_failed - before_f);
    }
    printf("TOTAL      %5d checks, %d failed\n", t_checks, t_failed);
    return t_failed ? 1 : 0;
}
