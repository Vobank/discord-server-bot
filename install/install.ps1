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
foreach ($s in @(@($name, 'control_panel.pyw', 'Панель управления'), @("$name — настройка", 'configure.pyw', 'Мастер настройки'))) {
    $l = $sh.CreateShortcut((Join-Path $desk ($s[0] + '.lnk')))
    $l.TargetPath = $vpyw
    $l.Arguments = '"' + (Join-Path $dst $s[1]) + '"'
    $l.WorkingDirectory = $dst
    $l.Description = $s[2]
    $l.Save()
}

if ($ready) {
    Step "5/5 Включаю автозапуск и запускаю"
    $startup = [Environment]::GetFolderPath('Startup')
    $vbs = Join-Path $dst 'tools\run_hidden.vbs'
    $have = $false
    Get-ChildItem $startup -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        if ($sh.CreateShortcut($_.FullName).Arguments -like "*$vbs*") { $have = $true } }
    if (-not $have) {
        $l = $sh.CreateShortcut((Join-Path $startup "$name (автозапуск).lnk"))
        $l.TargetPath = 'C:\Windows\System32\wscript.exe'
        $l.Arguments = '"' + $vbs + '"'
        $l.WorkingDirectory = $dst
        $l.Save()
    }
    Start-Process wscript.exe -ArgumentList ('"' + $vbs + '"')
    Start-Sleep 3
    Start-Process $vpyw -ArgumentList ('"' + (Join-Path $dst 'control_panel.pyw') + '"') -WorkingDirectory $dst
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "   ГОТОВО! Бот установлен и будет сам включаться вместе с ПК." -ForegroundColor Green
    Write-Host "   На рабочем столе ярлык «$name» — там видно, работает ли бот." -ForegroundColor Green
    Write-Host "   Папку с установщиком (архив) теперь можно удалить." -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
} else {
    Step "5/5 Открываю Мастер настройки"
    Start-Process $vpyw -ArgumentList ('"' + (Join-Path $dst 'configure.pyw') + '"') -WorkingDirectory $dst
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "   ГОТОВО! Программы установлены." -ForegroundColor Green
    Write-Host "   Открылся Мастер настройки — пройди вкладки слева направо," -ForegroundColor Green
    Write-Host "   потом «Построить сервер» и «Запустить бота»." -ForegroundColor Green
    Write-Host "   Бот лежит в папке $dst" -ForegroundColor Green
    Write-Host "=============================================" -ForegroundColor Green
}
