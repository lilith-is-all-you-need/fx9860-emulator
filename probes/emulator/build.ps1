param([string]$Compiler = 'C:\msys64\mingw64\bin\gcc.exe')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$upstream = Join-Path $root 'third_party/emuCasioCalc'
$build = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force -Path $build | Out-Null
$core = @('cpu.c','mem.c','sh7305.c','audio.c','r61524.c','t6k11.c','emu.c') | ForEach-Object { 'third_party/emuCasioCalc/src/engine/' + $_ }
$os = Get-ChildItem -LiteralPath (Join-Path $upstream 'src/engine/os') -Filter '*.c' | ForEach-Object { 'third_party/emuCasioCalc/src/engine/os/' + $_.Name }
$util = @('g3a.c','keys.c','png.c') | ForEach-Object { 'third_party/emuCasioCalc/src/utils/' + $_ }
$flags = @('-std=c11','-O2','-g','-Wall','-Wextra','-Wno-unused-parameter','-static','-include','probes/emulator/compat.h')
foreach ($inc in @('src/engine','src/engine/os','src/views','src/utils')) { $flags += '-I'; $flags += 'third_party/emuCasioCalc/' + $inc }
$sources = $core + $os + $util + @('probes/emulator/platform_headless.c', 'probes/emulator/probe.c')
Push-Location $root
try {
    & $Compiler @flags @sources '-lm' '-o' 'probes/emulator/build/preview-probe.exe' 2>&1 | Tee-Object -FilePath (Join-Path $build 'build.log')
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "Native probe build failed: $LASTEXITCODE" }
& $Compiler '--version' | Select-Object -First 1 | Set-Content (Join-Path $build 'compiler.txt')
git -C $upstream rev-parse HEAD | Set-Content (Join-Path $build 'upstream-commit.txt')
Get-FileHash -Algorithm SHA256 (Join-Path $build 'preview-probe.exe') | Format-List | Out-String | Set-Content (Join-Path $build 'sha256.txt')
