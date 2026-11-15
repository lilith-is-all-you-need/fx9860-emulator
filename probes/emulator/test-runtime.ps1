param([string]$Compiler = 'C:\msys64\mingw64\bin\gcc.exe', [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $root
try {
    & $PSScriptRoot/build-bridge.ps1 -Compiler $Compiler -Python $Python
    $core = @('cpu.c','mem.c','sh7305.c','audio.c','r61524.c','t6k11.c') | ForEach-Object { 'probes/emulator/build/patched/' + $_ }
    & $Compiler -std=c11 -O2 -g -static -include probes/emulator/compat.h -I probes/emulator/build/patched -I probes/emulator @core probes/emulator/hardware_model.c probes/emulator/test_hooks.c third_party/emuCasioCalc/tests/test_cpu.c -lm -o probes/emulator/build/test-cpu.exe
    if ($LASTEXITCODE -ne 0) { throw 'CPU regression build failed' }
    & ./probes/emulator/build/test-cpu.exe
    if ($LASTEXITCODE -ne 0) { throw 'CPU regression failed' }
    & $Python -X utf8 probes/emulator/test_runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Runtime regression failed' }
    & $Python -X utf8 probes/emulator/test_hardware.py
    if ($LASTEXITCODE -ne 0) { throw 'Hardware model regression failed' }
    & $Python -X utf8 probes/emulator/test_guest_refill.py
    if ($LASTEXITCODE -ne 0) { throw 'Guest refill regression failed' }
    & $Python -X utf8 probes/emulator/test_fx_syscalls.py -v
    if ($LASTEXITCODE -ne 0) { throw 'FX syscall regression failed' }
    & $Python -X utf8 probes/emulator/test_recovery.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Recovery regression failed' }
    & $Python -X utf8 probes/emulator/test_os_mapping.py -v
    if ($LASTEXITCODE -ne 0) { throw 'OS mapping regression failed' }
    & $Python -X utf8 probes/emulator/audit_syscalls.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Syscall coverage audit failed' }
} finally { Pop-Location }
