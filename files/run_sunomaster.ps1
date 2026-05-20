# SunoMaster v5.0 - PowerShell Launcher
# All answers collected here, passed to Python as arguments.

$ProjectDir = "E:\SunoMaster"
$ScriptPath = "$ProjectDir\scripts\sunomaster.py"
$PythonExe  = "C:\Dev\envs\sunomaster\python.exe"
$ReleasesDir= "$ProjectDir\releases"
$NormRefDir = "$ProjectDir\references\normalized reference tracks"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SunoMaster v5.0" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

foreach ($f in @("releases","collection","references","scripts","downloads",
                  "backup","shortened","output",
                  "references\normalized reference tracks")) {
    New-Item -ItemType Directory -Path "$ProjectDir\$f" -Force | Out-Null
}
Write-Host "Folders ready." -ForegroundColor Green

if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: sunomaster.py not found at $ScriptPath" -ForegroundColor Red
    Read-Host "Press Enter to exit"; exit 1
}
if (-not (Test-Path $PythonExe)) {
    Write-Host "Python not found. Installing environment..." -ForegroundColor Yellow

    conda create -n sunomaster python=3.10 -y

    Write-Host "Installing core packages..." -ForegroundColor Cyan
    conda run -n sunomaster pip install -q "numpy<2" scipy matplotlib soundfile librosa pyloudnorm tqdm colorama mutagen requests lxml pretty_midi music21

    Write-Host "Installing PyTorch CPU build (CUDA not available on Lenovo)..." -ForegroundColor Cyan
    conda run -n sunomaster pip install -q torch==2.2.2 torchaudio==2.2.2

    Write-Host "Installing audio ML packages..." -ForegroundColor Cyan
    conda run -n sunomaster pip install -q demucs basic-pitch
    conda run -n sunomaster pip install -q "setuptools<71"
    conda run -n sunomaster pip install -q crepe --no-build-isolation

    Write-Host "All dependencies installed." -ForegroundColor Green
}

# QUESTION 1 - Workstation
Write-Host ""
Write-Host "QUESTION 1 of 6 - Which workstation?" -ForegroundColor Yellow
Write-Host "  [1]  Lenovo ThinkStation  (E:\)"
Write-Host "  [2]  HP ZBook             (enter drive letter)"
$computer = Read-Host "Enter 1 or 2"
if ($computer -ne "1" -and $computer -ne "2") { $computer = "1" }
$drive = "E"
if ($computer -eq "2") {
    Write-Host "Enter drive letter only. Example: D" -ForegroundColor Yellow
    $drive = Read-Host "Drive letter"
    if (-not $drive) { $drive = "D" }
}

# QUESTION 2 - Genre
Write-Host ""
Write-Host "QUESTION 2 of 6 - Music genre (sets LUFS target)" -ForegroundColor Yellow
Write-Host "  [1]  underground  (-8.0 LUFS)  default"
Write-Host "  [2]  techno       (-7.5 LUFS)"
Write-Host "  [3]  house        (-8.0 LUFS)"
Write-Host "  [4]  deep_house   (-9.0 LUFS)"
Write-Host "  [5]  progressive  (-9.5 LUFS)"
Write-Host "  [6]  melodic      (-10.0 LUFS)"
Write-Host "  [7]  ambient      (-20.0 LUFS)"
$genreChoice = Read-Host "Enter 1-7 (or press Enter for default)"
$genreMap = @{"1"="underground";"2"="techno";"3"="house";"4"="deep_house";"5"="progressive";"6"="melodic";"7"="ambient"}
$genre = if ($genreMap.ContainsKey($genreChoice)) { $genreMap[$genreChoice] } else { "underground" }
Write-Host "  Genre: $genre" -ForegroundColor Green

# QUESTION 3 - Mode
Write-Host ""
Write-Host "QUESTION 3 of 6 - Processing mode" -ForegroundColor Yellow
Write-Host "  [1]  Single song"
Write-Host "  [2]  Batch - all songs in releases folder"
$mode = Read-Host "Enter 1 or 2"
if ($mode -ne "1" -and $mode -ne "2") { $mode = "1" }

# QUESTION 4 - Song folder (single only)
$songPath = ""
if ($mode -eq "1") {
    Write-Host ""
    Write-Host "QUESTION 4 of 6 - Song folder" -ForegroundColor Yellow
    Write-Host "Paste the full path to the song folder."
    Write-Host "Example: E:\SunoMaster\releases\05 Before the First Word (Agent WALL)"
    $songPath = (Read-Host "Song folder path").Trim().Trim('"')
} else {
    Write-Host ""
    Write-Host "QUESTION 4 of 6 - Batch: all songs in $ReleasesDir" -ForegroundColor Green
}

# QUESTION 5 - Reference track
Write-Host ""
Write-Host "QUESTION 5 of 6 - Reference track" -ForegroundColor Yellow
Write-Host "Paste the full path to your reference WAV."
Write-Host "Normalized references are in: $NormRefDir"
Write-Host "(Press Enter to skip - built-in profile will be used)"
$refPath = (Read-Host "Reference track path").Trim().Trim('"')

# QUESTION 6 - LetsSubmit
Write-Host ""
Write-Host "QUESTION 6 of 6 - LetsSubmit API key (optional)" -ForegroundColor Yellow
Write-Host "Paste your API key, or press Enter to skip."
$lsKey = (Read-Host "LetsSubmit API key").Trim()

# Summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Starting SunoMaster v5.0" -ForegroundColor Cyan
Write-Host "  Computer : $(if ($computer -eq '2') { 'HP ZBook (' + $drive + ':\)' } else { 'Lenovo ThinkStation (E:\)' })"
Write-Host "  Genre    : $genre"
Write-Host "  Mode     : $(if ($mode -eq '2') { 'Batch' } else { 'Single song' })"
if ($mode -eq "1") { Write-Host "  Song     : $songPath" }
Write-Host "  Reference: $(if ($refPath) { $refPath } else { 'Built-in profile' })"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

& $PythonExe $ScriptPath `
    --computer $computer `
    --drive    $drive `
    --mode     $mode `
    --song     $songPath `
    --ref      $refPath `
    --lskey    $lsKey `
    --genre    $genre

Write-Host ""
Write-Host "Session complete." -ForegroundColor Green
Read-Host "Press Enter to close"
