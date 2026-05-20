# SunoMaster v5.1
$ProjectDir = "E:\SunoMaster"
$ScriptPath = "$ProjectDir\scripts\sunomaster.py"
$PythonExe = "C:\Dev\envs\sunomaster\python.exe"
$ReleasesDir = "$ProjectDir\releases"
$NormRefDir = "$ProjectDir\references\normalized reference tracks"
Write-Host "SunoMaster v5.1" -ForegroundColor Cyan
foreach ($f in @("releases","collection","references","scripts","downloads","backup","shortened","output","references\normalized reference tracks")) { New-Item -ItemType Directory -Path "$ProjectDir\$f" -Force | Out-Null }
Write-Host "Folders ready." -ForegroundColor Green
if (-not (Test-Path $ScriptPath)) { Write-Host "ERROR: sunomaster.py not found" -ForegroundColor Red; Read-Host "Press Enter"; exit 1 }
if (-not (Test-Path $PythonExe)) { conda create -n sunomaster python=3.10 -y; conda run -n sunomaster pip install -q "numpy<2" scipy matplotlib soundfile librosa pyloudnorm tqdm colorama mutagen requests lxml pretty_midi music21; conda run -n sunomaster pip install -q torch==2.2.2 torchaudio==2.2.2; conda run -n sunomaster pip install -q demucs basic-pitch; conda run -n sunomaster pip install -q "setuptools<71"; conda run -n sunomaster pip install -q crepe --no-build-isolation }
Write-Host "Q1 - Workstation: [1] Lenovo  [2] HP ZBook" -ForegroundColor Yellow
$computer = Read-Host "Enter 1 or 2"
if ($computer -ne "1" -and $computer -ne "2") { $computer = "1" }
$drive = "E"
if ($computer -eq "2") { $drive = Read-Host "Enter drive letter"; if (-not $drive) { $drive = "D" } }
Write-Host "Q2 - Genre: [1]underground -8.0  [2]techno -7.5  [3]house -8.0  [4]deep_house -9.0  [5]progressive -9.5  [6]melodic -10.0  [7]ambient -20.0" -ForegroundColor Yellow
$gc = Read-Host "Enter 1-7 or Enter for default"
$gmap = @{"1"="underground";"2"="techno";"3"="house";"4"="deep_house";"5"="progressive";"6"="melodic";"7"="ambient"}
$genre = if ($gmap.ContainsKey($gc)) { $gmap[$gc] } else { "underground" }
Write-Host "Q3 - Mode: [1] Single song  [2] Batch" -ForegroundColor Yellow
$mode = Read-Host "Enter 1 or 2"
if ($mode -ne "1" -and $mode -ne "2") { $mode = "1" }
$songPath = ""
if ($mode -eq "1") { Write-Host "Q4 - Paste full song folder path" -ForegroundColor Yellow; $songPath = (Read-Host "Song folder").Trim() } else { Write-Host "Q4 - Batch mode" -ForegroundColor Green }
Write-Host "Q5 - Reference track path or Enter to skip" -ForegroundColor Yellow
$refPath = (Read-Host "Reference path").Trim()
Write-Host "Q6 - LetsSubmit API key or Enter to skip" -ForegroundColor Yellow
$lsKey = (Read-Host "API key").Trim()
Write-Host "Starting SunoMaster..." -ForegroundColor Cyan
& $PythonExe $ScriptPath --computer $computer --drive $drive --mode $mode --song $songPath --ref $refPath --lskey $lsKey --genre $genre
Write-Host "Done." -ForegroundColor Green
Read-Host "Press Enter to close"
