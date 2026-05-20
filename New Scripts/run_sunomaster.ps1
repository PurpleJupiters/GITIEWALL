# =============================================================
# SunoMaster v1.0 - PowerShell Runner
# Save sunomaster.py to E:\SunoMaster\scripts\ first
# Then run this script in PowerShell
# =============================================================

$RootDrive  = "E:"
$ProjectDir = "$RootDrive\SunoMaster"
$ScriptsDir = "$ProjectDir\scripts"
$ScriptPath = "$ScriptsDir\sunomaster.py"
$EnvName    = "sunomaster"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SunoMaster v1.0 - Setup & Launch" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Create folders if missing
$folders = @(
    "$ProjectDir\releases",
    "$ProjectDir\collection",
    "$ProjectDir\references",
    "$ProjectDir\scripts",
    "$ProjectDir\downloads",
    "$ProjectDir\backup",
    "$ProjectDir\shortened",
    "$ProjectDir\output"
)
foreach ($f in $folders) {
    New-Item -ItemType Directory -Path $f -Force | Out-Null
}
Write-Host "Folders verified." -ForegroundColor Green

# Check script exists
if (-not (Test-Path $ScriptPath)) {
    Write-Host ""
    Write-Host "ERROR: sunomaster.py not found at $ScriptPath" -ForegroundColor Red
    Write-Host "Please save sunomaster.py to that location first." -ForegroundColor Yellow
    Write-Host "(Copy from Claude chat into Notepad, File > Save As, All Files, name it sunomaster.py)"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "Script found: $ScriptPath" -ForegroundColor Green

# Check conda
$condaExists = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaExists) {
    Write-Host "conda not found. Please install Anaconda first." -ForegroundColor Red
    exit 1
}

# Create conda environment if it does not exist
$envList = conda env list 2>&1
if ($envList -notmatch $EnvName) {
    Write-Host ""
    Write-Host "Creating conda environment '$EnvName'..." -ForegroundColor Cyan
    conda create -n $EnvName python=3.10 -y
}

# Install all dependencies
Write-Host ""
Write-Host "Installing dependencies..." -ForegroundColor Cyan
conda run -n $EnvName pip install -q `
    numpy scipy matplotlib soundfile librosa pyloudnorm `
    torch torchaudio --index-url https://download.pytorch.org/whl/cu121 `
    demucs basic-pitch crepe pretty_midi music21 `
    lxml tqdm colorama mutagen requests

Write-Host "Dependencies installed." -ForegroundColor Green

# Run the pipeline
Write-Host ""
Write-Host "Launching SunoMaster..." -ForegroundColor Cyan
Write-Host ""
conda run -n $EnvName python $ScriptPath

Write-Host ""
Write-Host "SunoMaster session complete." -ForegroundColor Green
Read-Host "Press Enter to close"
