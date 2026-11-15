# C++17 runtime probe

This is a separate probe, not a modification of the existing C/C++ counter
examples. It uses the same native build service, target libraries, ELF/G1A
pairing checks, SuperH emulator and Windows GDB as the IDE.

`main.cpp` performs 16 rounds of actual `std::vector<int>` allocation/reserve,
push/erase operations, long `std::string` construction/append/replace/find/
compare, and nested RAII guards whose destructors increment a volatile counter.
The strings exceed the small-string buffer. It retains the two distinct nonzero
heap addresses as evidence, and draws the computed results before a named source
breakpoint. The target link map confirms inclusion of `libstdc++.a(new_op.o)`,
`del_ops.o`, `del_op.o`, `functexcept.o` and `string-inst.o`, including the real
malloc/free references. The probe does not replace global new/delete operators.

The project explicitly links `stdc++` before `Gint::Gint`: the SDK's
`-nostdlib` option suppresses g++'s automatic C++ standard-library linkage.
Omitting that library initially reproduced unresolved new/delete/string symbols.

Run from the repository root:

```text
python probes/emulator/test_cpp_runtime.py [native-sdk-prefix]
```

The successful Debug run used C++17, `-fno-exceptions`, `-Og -g3 -fno-lto` for
application compilation and `-flto-partition=none` for the prebuilt SDK library
link. Native GDB stopped in `runtime_complete()` and verified result 328,
destructors 32, rounds 16 and heap-check mask 63. The G1A is 39,120 bytes and all
38,608 payload bytes match its ELF. The fresh screen was also inspected and
shows `VECTOR/STRING: PASS`.

Evidence is in `../build/cpp-runtime/`: `results.json`, `build.log`,
`compiler-commands.jsonl`, `cpp-runtime.map`, `gdb-mi.log` and
`runtime-screen.png`. This verifies the exercised container/string/RAII
operations without exceptions or threads; it does not claim every standard
library facility or allocation-failure path has been validated.
