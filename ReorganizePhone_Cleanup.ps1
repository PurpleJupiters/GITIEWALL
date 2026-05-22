# ============================================================
# RONALD'S PHONE BACKUP - CLEANUP & FINISH SCRIPT
# Handles everything the main script left behind
# ============================================================

$src  = "E:\Project Backups\HonorPhoneBackup22MAY2026\sdcard"
$dst  = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$orig = "E:\HonorPhoneBackup22MAY2026\sdcard"
$log  = [System.Collections.Generic.List[string]]::new()
$moved = 0; $errors = 0

function Log($msg) { $script:log.Add("$(Get-Date -f 'HH:mm:ss')  $msg"); Write-Host $msg }

function EnsureDir($path) {
    if (!(Test-Path $path)) { New-Item -ItemType Directory -Force $path | Out-Null }
}

function MoveFiles($sourceDir, $filter, $destDir) {
    if (!(Test-Path $sourceDir)) { return }
    EnsureDir $destDir
    $files = Get-ChildItem $sourceDir -Filter $filter -File -Force -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        try { Move-Item $f.FullName -Destination $destDir -Force -EA Stop; $script:moved++ }
        catch { Log "  ERR: $($f.Name) - $_"; $script:errors++ }
    }
    if ($files.Count -gt 0) { Log "  Moved $($files.Count) [$filter] -> $destDir" }
}

function RoboCopyMove($srcDir, $dstDir) {
    if (!(Test-Path $srcDir)) { return }
    EnsureDir $dstDir
    $result = robocopy $srcDir $dstDir /E /MOVE /MT:4 /R:1 /W:1 /NP /NFL /NDL 2>&1
    Log "  Robocopy $srcDir -> $dstDir (exit $LASTEXITCODE)"
}

Log "CLEANUP START"

# ============================================================
# FIX ARCHIVES (currently a file, should be a folder)
# ============================================================
Log "`n-- FIX ARCHIVES --"
$archivesPath = "$dst\Archives"
if (Test-Path $archivesPath) {
    $item = Get-Item $archivesPath -Force
    if (!$item.PSIsContainer) {
        Remove-Item $archivesPath -Force
        Log "  Removed bad Archives file"
    }
}
EnsureDir "$dst\Archives\Download ZIPs"
# Copy ZIPs from original backup since they were lost
if (Test-Path "$orig\Download") {
    $zips = Get-ChildItem "$orig\Download" -Filter "*.zip" -File -Force -ErrorAction SilentlyContinue
    foreach ($z in $zips) {
        try { Copy-Item $z.FullName -Destination "$dst\Archives\Download ZIPs\" -Force -EA Stop; $script:moved++ }
        catch { Log "  ERR: $($z.Name)"; $script:errors++ }
    }
    Log "  Recovered $($zips.Count) ZIPs from original backup"
}

# ============================================================
# REMAINING DOWNLOAD FILES
# ============================================================
Log "`n-- DOWNLOAD REMAINING --"
$dlSrc = "$src\Download"
MoveFiles $dlSrc "*.mp3"  "$dst\Audio\Downloaded Audio\MP3"
MoveFiles $dlSrc "*.wav"  "$dst\Audio\Downloaded Audio\WAV"
MoveFiles $dlSrc "*.m4a"  "$dst\Audio\Downloaded Audio\M4A"
MoveFiles $dlSrc "*.mid"  "$dst\Audio\Compositions\MIDI\Other"
MoveFiles $dlSrc "*.docx" "$dst\Documents\Word"
MoveFiles $dlSrc "*.doc"  "$dst\Documents\Word"
MoveFiles $dlSrc "*.pdf"  "$dst\Documents\PDF"
MoveFiles $dlSrc "*.xlsx" "$dst\Documents\Spreadsheets\Excel"
MoveFiles $dlSrc "*.csv"  "$dst\Documents\Spreadsheets\CSV"
MoveFiles $dlSrc "*.txt"  "$dst\Documents\Text"
MoveFiles $dlSrc "*.html" "$dst\Documents\Web"
MoveFiles $dlSrc "*.svg"  "$dst\Documents\Web"
MoveFiles $dlSrc "*.py"   "$dst\Code\Python"
MoveFiles $dlSrc "*.jpg"  "$dst\Photos\Downloaded Images"
MoveFiles $dlSrc "*.jpeg" "$dst\Photos\Downloaded Images"
MoveFiles $dlSrc "*.png"  "$dst\Photos\Downloaded Images"
MoveFiles $dlSrc "*.webp" "$dst\Photos\Downloaded Images"
MoveFiles $dlSrc "*.mp4"  "$dst\Video\Downloaded"
# Anything left
$remaining = Get-ChildItem $dlSrc -File -Force -ErrorAction SilentlyContinue
if ($remaining.Count -gt 0) {
    EnsureDir "$dst\Archives\Download Misc"
    $remaining | ForEach-Object {
        try { Move-Item $_.FullName -Destination "$dst\Archives\Download Misc\" -Force -EA Stop; $script:moved++ }
        catch { $script:errors++ }
    }
    Log "  $($remaining.Count) misc Download files -> Archives\Download Misc"
}

# ============================================================
# MyDocuments (both with and without leading space)
# ============================================================
Log "`n-- MyDocuments --"
foreach ($mdName in @(" MyDocuments","MyDocuments")) {
    $mdSrc = "$src\$mdName"
    MoveFiles $mdSrc "*.cmake" "$dst\Code\Dev Libraries"
    MoveFiles $mdSrc "*.pc"    "$dst\Code\Dev Libraries"
    MoveFiles $mdSrc "*.so"    "$dst\Code\Dev Libraries"
    MoveFiles $mdSrc "*.h"     "$dst\Code\Dev Libraries"
    MoveFiles $mdSrc "*.py"    "$dst\Code\Python"
    MoveFiles $mdSrc "*.mp3"   "$dst\Audio\Downloaded Audio\MP3"
    MoveFiles $mdSrc "*.m4a"   "$dst\Audio\Downloaded Audio\M4A"
    MoveFiles $mdSrc "*.mp4"   "$dst\Video\Downloaded"
    MoveFiles $mdSrc "*.wav"   "$dst\Audio\Downloaded Audio\WAV"
    MoveFiles $mdSrc "*.pdf"   "$dst\Documents\PDF"
    MoveFiles $mdSrc "*.zip"   "$dst\Code\Projects\MyDocuments Archives"
    # Anything left
    $rem = Get-ChildItem $mdSrc -File -Force -ErrorAction SilentlyContinue
    if ($rem.Count -gt 0) {
        EnsureDir "$dst\Archives\MyDocuments Misc"
        $rem | ForEach-Object {
            try { Move-Item $_.FullName -Destination "$dst\Archives\MyDocuments Misc\" -Force -EA Stop; $script:moved++ }
            catch { $script:errors++ }
        }
    }
}

# ============================================================
# DOCUMENTS folder
# ============================================================
Log "`n-- Documents folder --"
$docSrc = "$src\Documents"
MoveFiles $docSrc "*.docx" "$dst\Documents\Word"
MoveFiles $docSrc "*.pdf"  "$dst\Documents\PDF"
MoveFiles $docSrc "*.txt"  "$dst\Documents\Text"
MoveFiles $docSrc "*.png"  "$dst\Photos\Downloaded Images"

# ============================================================
# MUSIC folder (remaining)
# ============================================================
Log "`n-- Music remaining --"
MoveFiles "$src\Music" "*.mp3"  "$dst\Audio\Music Library\MP3"
MoveFiles "$src\Music" "*.m4a"  "$dst\Audio\Music Library\M4A"
MoveFiles "$src\Music" "*.docx" "$dst\Documents\Word"
MoveFiles "$src\Music" "*.jpg"  "$dst\Ronald's Trash Folder\App Temp\MusicCovers"

# ============================================================
# SOUNDS folder (remaining - jpg covers and txt)
# ============================================================
Log "`n-- Sounds remaining --"
MoveFiles "$src\Sounds" "*.jpg"    "$dst\Ronald's Trash Folder\App Temp\SoundCovers"
MoveFiles "$src\Sounds" "*.txt"    "$dst\Ronald's Trash Folder\App Temp\SoundCovers"
MoveFiles "$src\Sounds" "*.nomedia" "$dst\Ronald's Trash Folder\App Temp\SoundCovers"

# ============================================================
# NOTIFICATIONS folder
# ============================================================
Log "`n-- Notifications --"
MoveFiles "$src\Notifications" "*.m4a" "$dst\Audio\Sound Libraries\Notifications"
MoveFiles "$src\Notifications" "*.mp3" "$dst\Audio\Sound Libraries\Notifications"
MoveFiles "$src\Notifications" "*.ogg" "$dst\Audio\Sound Libraries\Notifications"

# ============================================================
# PICTURES remaining subfolders
# ============================================================
Log "`n-- Pictures remaining --"
if (Test-Path "$src\Pictures") {
    Get-ChildItem "$src\Pictures" -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.PSIsContainer) {
            $destSub = "$dst\Photos\App Photos\$($_.Name)"
            try { Move-Item $_.FullName -Destination $destSub -Force -EA Stop; $script:moved++ }
            catch { Log "  ERR folder: $($_.Name)"; $script:errors++ }
        } else {
            EnsureDir "$dst\Photos\App Photos"
            try { Move-Item $_.FullName -Destination "$dst\Photos\App Photos\" -Force -EA Stop; $script:moved++ }
            catch { $script:errors++ }
        }
    }
}

# ============================================================
# DCIM remaining (1 PNG)
# ============================================================
Log "`n-- DCIM remaining --"
MoveFiles "$src\DCIM" "*.png" "$dst\Photos\Downloaded Images"
Get-ChildItem "$src\DCIM" -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
    EnsureDir "$dst\Photos\Camera\Unsorted"
    try { Move-Item $_.FullName -Destination "$dst\Photos\Camera\Unsorted\" -Force -EA Stop; $script:moved++ }
    catch { $script:errors++ }
}

# ============================================================
# HIDDEN FOLDERS using robocopy (handles long paths)
# ============================================================
Log "`n-- Hidden folders (robocopy) --"
RoboCopyMove "$src\.File_Recycle"  "$dst\Ronald's Trash Folder\Deleted Files"
RoboCopyMove "$src\.archivetemp"   "$dst\Ronald's Trash Folder\App Temp\.archivetemp"
RoboCopyMove "$src\.fileMOShare"   "$dst\Ronald's Trash Folder\App Temp\.fileMOShare"
RoboCopyMove "$src\.mixplorer"     "$dst\Ronald's Trash Folder\App Temp\.mixplorer"

# ============================================================
# CLEAN UP EMPTY FOLDERS IN SDCARD
# ============================================================
Log "`n-- Cleanup empty folders in sdcard --"
Get-ChildItem $src -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending |
    Where-Object { (Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue).Count -eq 0 } |
    ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }

# Check if sdcard itself is now empty
$remaining = (Get-ChildItem $src -Force -ErrorAction SilentlyContinue).Count
if ($remaining -eq 0) {
    Remove-Item $src -Force -ErrorAction SilentlyContinue
    Log "  sdcard folder is now empty and removed"
} else {
    Log "  sdcard still has $remaining items - check manually"
    Get-ChildItem $src -Force -ErrorAction SilentlyContinue | ForEach-Object { Log "    Remaining: $($_.Name)" }
}

# ============================================================
# FINAL STRUCTURE REPORT
# ============================================================
Log "`n-- FINAL STRUCTURE --"
Get-ChildItem $dst -Force | ForEach-Object {
    if ($_.PSIsContainer) {
        $c = (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue).Count
        $s = (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum -ErrorAction SilentlyContinue).Sum / 1MB
        Log "  $($_.Name.PadRight(35)) $c files   $([math]::Round($s,0)) MB"
    }
}

Log "`n================================================"
Log "CLEANUP COMPLETE"
Log "  Additional items moved : $moved"
Log "  Errors                 : $errors"
Log "================================================"

$script:log | Add-Content "$dst\REORGANIZATION_LOG.txt" -Encoding UTF8
Write-Host "Done. Log appended to $dst\REORGANIZATION_LOG.txt"
