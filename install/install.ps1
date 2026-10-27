# Установщик бота. Запускается из УСТАНОВИТЬ.bat — ничего делать руками не нужно.
# Ставит Python, FFmpeg, Deno, копирует бота в %USERPROFILE%\DiscordBot, ставит библиотеки.
# Если ключ бота уже есть (архив для второго ПК) — включает автозапуск и запускает бота,
# иначе открывает Мастер настройки.
$ErrorActionPreference = 'Continue'
$src = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dst = Join-Path $env:USERPROFILE 'DiscordBot'

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function RefreshPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

# Имя бота — из настроек (для ярлыков)
$name = 'Discord Bot'
foreach ($f in @('settings.json', 'settings.example.json')) {
    $p = Join-Path $src $f
    if (Test-Path $p) {
        try { $j = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json; if ($j.bot.name) { $name = $j.bot.name; break } } catch {}
    }
}
$name = ($name -replace '[\\/:*?"<>|]', '').Trim()
if (-not $name) { $name = 'Discord Bot' }

Write-Host "=============================================" -ForegroundColor Magenta
Write-Host "   Установка «$name» — просто подожди 5-10 минут" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta

if (-not (Have winget)) {
    Write-Host "Нет программы winget. Открой Microsoft Store, найди «Установщик приложений» (App Installer), обнови его и запусти установку снова." -ForegroundColor Red
    exit 1
}

Step "1/5 Ставлю нужные программы (Python, FFmpeg, Deno)"
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
if (-not (Test-Path $py)) {
    winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
}
winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements | Out-Null
winget install -e --id DenoLand.Deno --silent --accept-package-agreements --accept-source-agreements | Out-Null
RefreshPath
if (-not (Test-Path $py)) {
    $found = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python') -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $py = $found.FullName } elseif (Have python) { $py = (Get-Command python).Source }
}
if (-not (Test-Path $py)) { Write-Host "Не получилось установить Python. Перезагрузи ПК и запусти установку снова." -ForegroundColor Red; exit 1 }
Write-Host "Python: $py"

Step "2/5 Копирую бота в $dst"
if ((Resolve-Path $src).Path -ne $dst) {
    robocopy $src $dst /E /XD .venv runtime __pycache__ .git /NFL /NDL /NJH /NJS /NP | Out-Null
}
New-Item -ItemType Directory -Force (Join-Path $dst 'runtime') | Out-Null

Step "3/5 Ставлю библиотеки бота (самое долгое)"
& $py -m venv (Join-Path $dst '.venv')
$vpy = Join-Path $dst '.venv\Scripts\python.exe'
$vpyw = Join-Path $dst '.venv\Scripts\pythonw.exe'
& $vpy -m pip install -q --upgrade pip
& $vpy -m pip install -q -r (Join-Path $dst 'requirements.txt')

$envFile = Join-Path $dst '.env'
$ready = (Test-Path $envFile) -and ((Get-Content $envFile -Raw) -match '(?m)^DISCORD_TOKEN=\S{50,}')

Step "4/5 Ярлыки на рабочем столе"
$sh = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath('Desktop')
# старые ярлыки панели и мастера настройки (прошлые версии) — убираем, теперь всё в одной программе
Get-ChildItem $desk -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
    $a = $sh.CreateShortcut($_.FullName).Arguments
    if ($a -like ('*' + (Join-Path $dst 'control_panel.pyw') + '*') -or $a -like ('*' + (Join-Path $dst 'configure.pyw') + '*')) { Remove-Item $_.FullName }
}
$l = $sh.CreateShortcut((Join-Path $desk ($name + '.lnk')))
$l.TargetPath = $vpyw
$l.Arguments = '"' + (Join-Path $dst 'manager.pyw') + '"'
$l.WorkingDirectory = $dst
$l.Description = 'Панель управления ботом'
$ico = Join-Path $dst 'assets\icon.ico'
if (Test-Path $ico) { $l.IconLocation = $ico }
$l.Save()

if ($ready) {
    Step "5/5 Включаю автозапуск и запускаю"
    $startup = [Environment]::GetFolderPath('Startup')
    # автозапуск через pythonw без окна; старый ярлык через VBScript убираем — VBScript есть не во всех Windows
    $launcher = Join-Path $dst 'tools\autostart.pyw'
    $vbs = Join-Path $dst 'tools\run_hidden.vbs'
    Get-ChildItem $startup -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        $a = $sh.CreateShortcut($_.FullName).Arguments
        if ($a -like "*$vbs*" -or $a -like "*$launcher*") { Remove-Item $_.FullName } }
    $l = $sh.CreateShortcut((Join-Path $startup "$name (автозапуск).lnk"))
    $l.TargetPath = $vpyw
    $l.Arguments = '"' + $launcher + '"'
    $l.WorkingDirectory = $dst
    $l.Save()
    Start-Process $vpyw -ArgumentList ('"' + $launcher + '"') -WorkingDirectory $dst
    Start-Sleep 3
    Start-Process $vpyw -ArgumentList ('"' + (Join-Path $dst 'manager.pyw') + '"') -WorkingDirectory $dst
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "   Готово. Бот установлен и будет сам включаться вместе с ПК." -ForegroundColor Green
    Write-Host "   Ярлык «$name» на рабочем столе открывает панель управления." -ForegroundColor Green
    Write-Host "   Папку с установщиком (архив) теперь можно удалить." -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
} else {
    Step "5/5 Открываю панель управления"
    Start-Process $vpyw -ArgumentList ('"' + (Join-Path $dst 'manager.pyw') + '" --page connection') -WorkingDirectory $dst
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "   Готово. Программы установлены." -ForegroundColor Green
    Write-Host "   Открылась панель управления: укажите ключ бота в разделе «Подключение»," -ForegroundColor Green
    Write-Host "   затем «Обзор» подскажет следующие шаги." -ForegroundColor Green
    Write-Host "   Бот лежит в папке $dst" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
}
