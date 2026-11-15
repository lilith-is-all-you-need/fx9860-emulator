param([string]$Compiler = 'C:\msys64\mingw64\bin\gcc.exe', [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $root
try {
    $upstreamRoot = Join-Path $root 'third_party/emuCasioCalc'
    if (Test-Path (Join-Path $upstreamRoot '.git')) {
        $upstreamCommit = (git -C $upstreamRoot rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not identify emulator source revision' }
    } else {
        # Corresponding-source archives deliberately do not contain Git metadata.
        $origin = Get-Content -Raw -LiteralPath (Join-Path $upstreamRoot 'SOURCE-ORIGIN.json') | ConvertFrom-Json
        $upstreamCommit = $origin.revision
    }
    if ($upstreamCommit -ne '63e325708e9eea53eb4769b9c057082614ebd919') { throw 'Unexpected emulator upstream revision' }
    & $Python probes/emulator/prepare_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare source hooks' }
    $core = @('cpu.c','mem.c','sh7305.c','audio.c','r61524.c','t6k11.c','emu.c') | ForEach-Object { 'probes/emulator/build/patched/' + $_ }
    $os = Get-ChildItem probes/emulator/build/patched/os -Filter '*.c' | ForEach-Object { 'probes/emulator/build/patched/os/' + $_.Name }
    $util = @('g3a.c','keys.c','png.c') | ForEach-Object { 'third_party/emuCasioCalc/src/utils/' + $_ }
    $flags = @('-std=c11','-O2','-g','-Wall','-Wextra','-Wno-unused-parameter','-static','-municode','-include','probes/emulator/bridge_compat.h')
    foreach ($inc in @('probes/emulator/build/patched','probes/emulator','probes/emulator/build/patched/os','third_party/emuCasioCalc/src/views','third_party/emuCasioCalc/src/utils')) { $flags += '-I'; $flags += $inc }
    $sources = $core + $os + $util + @('probes/emulator/hardware_model.c', 'probes/emulator/syscall_trace.c', 'probes/emulator/bridge_platform.c', 'probes/emulator/bridge.c')
    Set-Content -LiteralPath probes/emulator/build/bridge-build.log -Value ''
    & $Compiler @flags @sources '-lm' '-lws2_32' '-o' 'probes/emulator/build/FxEmulator.exe' 2>&1 | Tee-Object -FilePath probes/emulator/build/bridge-build.log
    if ($LASTEXITCODE -ne 0) { throw "Bridge build failed: $LASTEXITCODE" }
    $manifest = [ordered]@{
        upstreamCommit = $upstreamCommit
        compiler = (& $Compiler --version | Select-Object -First 1)
        executable = 'FxEmulator.exe'
        bytes = (Get-Item probes/emulator/build/FxEmulator.exe).Length
        sha256 = (Get-FileHash probes/emulator/build/FxEmulator.exe -Algorithm SHA256).Hash.ToLowerInvariant()
        sourcePatchSha256 = (Get-FileHash probes/emulator/debugger-hooks.patch -Algorithm SHA256).Hash.ToLowerInvariant()
        compatibilityPatchSha256 = (Get-FileHash probes/emulator/runtime-compat.patch -Algorithm SHA256).Hash.ToLowerInvariant()
        bridgeSources = @('hardware_model.c', 'hardware_model.h', 'heap_compat.h', 'memory_compat.h', 'fx_syscalls.h', 'file_map_compat.h', 'file_address_compat.h', '../os-map-profile.h', '../os-map-hashes.h', 'recovery.h', 'syscall_trace.c', 'syscall_trace.h',
            'bridge.c', 'bridge_platform.c', 'bridge_compat.h', 'compat.h', 'debug_bridge.h',
            'prepare_sources.py', 'build-bridge.ps1') | ForEach-Object {
            [ordered]@{ name = $_; sha256 = (Get-FileHash (Join-Path $PSScriptRoot $_) -Algorithm SHA256).Hash.ToLowerInvariant() }
        }
        architecture = 'Windows x64'
    }
    $manifest | ConvertTo-Json | Set-Content -Encoding utf8 probes/emulator/build/BUILD-MANIFEST.json
} finally { Pop-Location }
