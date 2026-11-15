# fx9860-emulator

Windows SH7305 emulator, GDB remote bridge, FX syscall models and fault evidence.
This is a functional HLE model, not a full Casio OS implementation.

```
git submodule update --init
pwsh ./probes/emulator/test-runtime.ps1 -Compiler C:/msys64/mingw64/bin/gcc.exe -Python python
```

Output: `probes/emulator/build/FxEmulator.exe`. CPU, runtime, MMU/cache, syscall,
recovery and guest-refill tests run locally and in Windows CI. Optional firmware
tests use `FX_TEST_FIRMWARE`; no proprietary OS image is distributed.

Guest RAM VBR refill and fault retry regressions cover automatic external-file
execution beyond the OS 2 MiB window. The OS table itself remains 512 pages.

See [backend documentation](probes/emulator/README.md) and
[coverage](probes/emulator/SYSCALL-COVERAGE.md). Upstream emuCasioCalc is pinned as
a submodule; retain its MIT and font licenses when distributing a binary.
FxStudio integrates a version-pinned source snapshot; this repository owns the
emulator component. Shared OS profile headers are hash-checked in that snapshot.
