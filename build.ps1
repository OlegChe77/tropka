# Сборка «Тропки» в один файл: dist\Tropka.exe
# Запуск: powershell -ExecutionPolicy Bypass -File build.ps1
# Нужно: pip install -r requirements.txt pyinstaller
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$root = $PSScriptRoot
$work = Join-Path $root "build"

# Значок и версия (берётся из most/__init__.py)
python packaging\make_assets.py $work
if ($LASTEXITCODE -ne 0) { throw "Не удалось подготовить значок и версию" }

# Что кладётся в exe и что выкидывается — в packaging\most.spec
python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $root "dist") --workpath $work `
    (Join-Path $root "packaging\most.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }

$exe = Get-Item (Join-Path $root "dist\Tropka.exe")
"Готово: $($exe.FullName) ($([math]::Round($exe.Length / 1MB, 1)) МБ)"
