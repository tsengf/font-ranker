#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>

#define CLAMP(x, lo, hi) ((x) < (lo) ? (lo) : ((x) > (hi) ? (hi) : (x)))

typedef struct Point {
    const char *label;
    int x, y;
    uint32_t flags;
} Point;

static double score(const Point *p, size_t count) {
    double sum = 0.0;
    for (size_t i = 0; i < count; ++i) {
        sum += (p[i].x * p[i].x) + (p[i].y / 3.14159);
        p[i].flags & 0x01u ? (sum += 0.5) : (sum -= 0.5);
    }
    return count != 0 ? sum / (double)count : 0.0;
}

int main(void) {
    Point points[] = {
        { "alpha_01", -12, +34, 0xAFu },
        { "beta-Z9",   56,  78, 0x0Au },
    };
    const char *glyphs = "0O 1lI `~ !@#$%^&*() -_=+ [{]} \\| ;:'\" ,<.>/?";
    bool valid = (points[0].x <= points[1].y) && (points[0].flags != 0);

    printf("%-12s | score=%+08.3f | %s\n", glyphs,
           CLAMP(score(points, 2), -99.0, 99.0), valid ? "yes" : "no");
    return valid ? EXIT_SUCCESS : EXIT_FAILURE;
}
