#include <gint/display.h>
#include <gint/keyboard.h>
#include <cstdint>
#include <string>
#include <vector>

volatile int runtime_result = -1;
volatile unsigned destructor_count = 0;
volatile unsigned heap_checks = 0;
volatile unsigned completed_rounds = 0;
volatile std::uintptr_t vector_buffer = 0;
volatile std::uintptr_t string_buffer = 0;

struct ScopeGuard {
    std::string storage;
    explicit ScopeGuard(const char *text) : storage(text) {}
    ~ScopeGuard() { ++destructor_count; }
};

__attribute__((noinline)) int exercise_runtime(int seed)
{
    int total = 0;
    {
        ScopeGuard outer("outer RAII member also allocates a real long string");
        std::vector<int> values;
        values.reserve(32);
        for (int i = 1; i <= 12; ++i) values.push_back(i * seed);
        if (values.capacity() >= 32 && values.size() == 12) heap_checks |= 1;
        vector_buffer = reinterpret_cast<std::uintptr_t>(values.data());
        for (int value : values) total += value;
        values.erase(values.begin() + 1); // Remove 2 * seed, move remaining items.
        values.push_back(100);
        if (values.size() == 12 && values.front() == seed && values.back() == 100)
            heap_checks |= 2;
        total = total - 2 * seed + values.back();
        {
            ScopeGuard inner("inner RAII member: another heap allocated string");
            std::string text("fx9860giii native C++17 runtime uses dynamic storage");
            text += " / vector + string";
            text.replace(0, 10, "FX9860GIII");
            if (text.size() > 32 && text.capacity() >= text.size()) heap_checks |= 4;
            string_buffer = reinterpret_cast<std::uintptr_t>(text.data());
            if (text.find("vector + string") != std::string::npos &&
                text.compare(0, 10, "FX9860GIII") == 0) heap_checks |= 8;
        }
        if (destructor_count % 2 == 1) heap_checks |= 16;
    }
    if (destructor_count % 2 == 0 && vector_buffer && string_buffer &&
        vector_buffer != string_buffer) heap_checks |= 32;
    return total;
}

__attribute__((noinline)) void runtime_complete()
{
    // Stable source breakpoint after all containers and guards were destroyed.
    asm volatile ("" ::: "memory");
}

int main()
{
    // Repeated construction/destruction also catches obvious heap-lifetime faults.
    for (int round = 0; round < 16; ++round) {
        runtime_result = exercise_runtime(3);
        ++completed_rounds;
    }
    dclear(C_WHITE);
    dtext(2, 1, C_BLACK, "C++17 RUNTIME");
    dprint(2, 14, C_BLACK, "Result: %d", runtime_result);
    dprint(2, 26, C_BLACK, "RAII: %u  Rounds: %u", destructor_count, completed_rounds);
    dprint(2, 38, C_BLACK, "Heap checks: %u/63", heap_checks);
    dtext(2, 51, C_BLACK,
        runtime_result == 328 && destructor_count == 32 && heap_checks == 63
        ? "VECTOR/STRING: PASS" : "RUNTIME: FAIL");
    dupdate();
    runtime_complete();
    while (getkey().key != KEY_EXIT) {}
    return 0;
}
