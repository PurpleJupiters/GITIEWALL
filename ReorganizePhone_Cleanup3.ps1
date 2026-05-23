# ============================================================
# RONALD'S PHONE BACKUP - CLEANUP 3
# Robocopy returned exit 0 on many folders (files already existed
# at destination so nothing was copied, nothing was deleted from source).
# This script re-runs all those moves with /IS /IT flags to force-move
# even files that match at destination, then cleans empty dirs.
# ============================================================

$src  = "E:\Project Backups\HonorPhoneBackup22MAY2026\sdcard"
$dst  = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$log  = [System.Collections.Generic.List[string]]::new()

function Log($msg) { $script:log.Add("$(Get-Date -f 'HH:mm:ss')  $msg"); Write-Host $msg }

function EnsureDir($path) {
    if (!(Test-Path $path)) { New-Item -ItemType Directory -Force $path | Out-Null }
}

function ForceMove($srcDir, $dstDir) {
    if (!(Test-Path $srcDir)) { Log "  SKIP (not found): $srcDir"; return }
    EnsureDir $dstDir
    $before = (Get-ChildItem $srcDir -Recurse -File -Force -ErrorAction SilentlyContinue).Count
    # /IS = include same files, /IT = include tweaked files
    # Forces robocopy to re-copy even if file already exists at dest, then /MOVE deletes source
    robocopy $srcDir $dstDir /E /MOVE /IS /IT /MT:4 /R:1 /W:1 /NP /NFL /NDL 2>&1 | Out-Null
    $after = (Get-ChildItem $srcDir -Recurse -File -Force -ErrorAction SilentlyContinue).Count
    Log "  ForceMove: $srcDir -> $dstDir (exit $LASTEXITCODE, was $before, remaining $after)"
}

function MoveFiles($sourceDir, $filter, $destDir) {
    if (!(Test-Path $sourceDir)) { return }
    EnsureDir $destDir
    $files = Get-ChildItem $sourceDir -Filter $filter -File -Force -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        try { Move-Item $f.FullName -Destination $destDir -Force -EA Stop }
        catch { Log "  ERR: $($f.Name) - $_" }
    }
    if ($files.Count -gt 0) { Log "  Moved $($files.Count) [$filter] from $(Split-Path $sourceDir -Leaf) -> $destDir" }
}

Log "CLEANUP3 START"
Log "sdcard source: $src"
Log "Strategy: robocopy /IS /IT to force-move files even if already at destination`n"

# ============================================================
# LARGE SYSTEM/MEDIA FOLDERS (same mappings as Cleanup2)
# ============================================================
Log "-- Large folders (force-move) --"
ForceMove "$src\Honor"         "$dst\System - Do Not Touch\Honor App Data"
ForceMove "$src\Movies"        "$dst\Video\Downloaded"
ForceMove "$src\Music"         "$dst\Audio\Music Library"
ForceMove "$src\Sounds"        "$dst\Audio\Sound Libraries\Sounds"
ForceMove "$src\Notifications" "$dst\Audio\Sound Libraries\Notifications"

# ============================================================
# SOUND LIBRARIES
# ============================================================
Log "`n-- Sound Libraries (force-move) --"
ForceMove "$src\sound_effects"         "$dst\Audio\Sound Libraries\Sound Effects"
ForceMove "$src\nasa_sounds"           "$dst\Audio\Sound Libraries\NASA"
ForceMove "$src\youtube_sounds"        "$dst\Audio\Sound Libraries\YouTube"
ForceMove "$src\working_sound_effects" "$dst\Audio\Sound Libraries\Working"
ForceMove "$src\test_sounds"           "$dst\Audio\Sound Libraries\Test"
ForceMove "$src\TimidityAE"            "$dst\Audio\Sound Libraries\TimidityAE"

# ============================================================
# VOICE WORK
# ============================================================
Log "`n-- Voice Work (force-move) --"
ForceMove "$src\VoiceToMidi"   "$dst\Audio\Voice Work\Voice to MIDI"
ForceMove "$src\VoiceToText"   "$dst\Audio\Voice Work\Voice to Text"
ForceMove "$src\Recorder 2026" "$dst\Audio\Voice Work\Voice Memos"

# ============================================================
# CODE / PROJECTS
# ============================================================
Log "`n-- Code Projects (force-move) --"
ForceMove "$src\Ronald Pyroid"   "$dst\Code\Projects\Ronald Pyroid"
ForceMove "$src\MPA Competition" "$dst\Audio\MPA Competition"

# ============================================================
# SYSTEM FOLDERS
# ============================================================
Log "`n-- System folders (force-move) --"
ForceMove "$src\HonorSystem"   "$dst\System - Do Not Touch\HonorSystem"
ForceMove "$src\Huawei"        "$dst\System - Do Not Touch\Huawei"
ForceMove "$src\tencent"       "$dst\System - Do Not Touch\tencent"
ForceMove "$src\SystemAndroid" "$dst\System - Do Not Touch\SystemAndroid"
ForceMove "$src\pictorial"     "$dst\System - Do Not Touch\pictorial"
ForceMove "$src\magazine"      "$dst\Ronald's Trash Folder\App Temp\magazine"
ForceMove "$src\Koala"         "$dst\Ronald's Trash Folder\App Temp\Koala"
ForceMove "$src\DownloadHelper" "$dst\Ronald's Trash Folder\App Temp\DownloadHelper"

# ============================================================
# MyDocuments (both variants)
# ============================================================
Log "`n-- MyDocuments (force-move) --"
foreach ($mdName in @(" MyDocuments","MyDocuments")) {
    $mdSrc = "$src\$mdName"
    if (!(Test-Path $mdSrc)) { continue }
    # Extension sorts first
    MoveFiles $mdSrc "*.py"    "$dst\Code\Python"
    MoveFiles $mdSrc "*.mp3"   "$dst\Audio\Downloaded Audio\MP3"
    MoveFiles $mdSrc "*.m4a"   "$dst\Audio\Downloaded Audio\M4A"
    MoveFiles $mdSrc "*.wav"   "$dst\Audio\Downloaded Audio\WAV"
    MoveFiles $mdSrc "*.mp4"   "$dst\Video\Downloaded"
    MoveFiles $mdSrc "*.pdf"   "$dst\Documents\PDF"
    MoveFiles $mdSrc "*.docx"  "$dst\Documents\Word"
    MoveFiles $mdSrc "*.txt"   "$dst\Documents\Text"
    MoveFiles $mdSrc "*.zip"   "$dst\Code\Projects\MyDocuments Archives"
    # Root-level remainder
    $rem = Get-ChildItem $mdSrc -File -Force -ErrorAction SilentlyContinue
    if ($rem.Count -gt 0) {
        EnsureDir "$dst\Archives\MyDocuments Misc"
        $rem | ForEach-Object {
            try { Move-Item $_.FullName -Destination "$dst\Archives\MyDocuments Misc\" -Force -EA Stop }
            catch { Log "  ERR: $($_.Name) - $_" }
        }
        Log "  Moved $($rem.Count) misc files from $mdName root -> Archives\MyDocuments Misc"
    }
    # Subfolders - force-move
    $subFolders = Get-ChildItem $mdSrc -Directory -Force -ErrorAction SilentlyContinue
    foreach ($sf in $subFolders) {
        ForceMove $sf.FullName "$dst\Archives\MyDocuments\$($sf.Name)"
    }
}

# ============================================================
# DOCUMENTS folder remnant
# ============================================================
Log "`n-- Documents remnant --"
MoveFiles "$src\Documents" "*.docx" "$dst\Documents\Word"
MoveFiles "$src\Documents" "*.pdf"  "$dst\Documents\PDF"
MoveFiles "$src\Documents" "*.txt"  "$dst\Documents\Text"
MoveFiles "$src\Documents" "*.png"  "$dst\Photos\Downloaded Images"
$docRem = Get-ChildItem "$src\Documents" -File -Force -ErrorAction SilentlyContinue
if ($docRem.Count -gt 0) {
    EnsureDir "$dst\Archives\Documents Misc"
    $docRem | ForEach-Object {
        try { Move-Item $_.FullName -Destination "$dst\Archives\Documents Misc\" -Force -EA Stop }
        catch { Log "  ERR: $($_.Name) - $_" }
    }
    Log "  $($docRem.Count) misc docs -> Archives\Documents Misc"
}
# Doc subfolders
Get-ChildItem "$src\Documents" -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
    ForceMove $_.FullName "$dst\Archives\Documents Misc\$($_.Name)"
}

# ============================================================
# DOWNLOAD remnant (anything left after Cleanup2)
# ============================================================
Log "`n-- Download remnant --"
$dl = "$src\Download"
# Extension sorts for anything still there
MoveFiles $dl "*.mp3"   "$dst\Audio\Downloaded Audio\MP3"
MoveFiles $dl "*.wav"   "$dst\Audio\Downloaded Audio\WAV"
MoveFiles $dl "*.m4a"   "$dst\Audio\Downloaded Audio\M4A"
MoveFiles $dl "*.mp4"   "$dst\Video\Downloaded"
MoveFiles $dl "*.jpg"   "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.jpeg"  "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.png"   "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.docx"  "$dst\Documents\Word"
MoveFiles $dl "*.pdf"   "$dst\Documents\PDF"
MoveFiles $dl "*.txt"   "$dst\Documents\Text"
MoveFiles $dl "*.zip"   "$dst\Archives\Download ZIPs"
MoveFiles $dl "*.py"    "$dst\Code\Python"
# Subfolders of Download
Get-ChildItem $dl -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
    ForceMove $_.FullName "$dst\Archives\Download Misc\$($_.Name)"
}
# Remaining files
$dlRem = Get-ChildItem $dl -File -Force -ErrorAction SilentlyContinue
if ($dlRem.Count -gt 0) {
    EnsureDir "$dst\Archives\Download Misc"
    $dlRem | ForEach-Object {
        try { Move-Item $_.FullName -Destination "$dst\Archives\Download Misc\" -Force -EA Stop }
        catch { Log "  ERR: $($_.Name) - $_" }
    }
    Log "  $($dlRem.Count) remaining Download files -> Archives\Download Misc"
}

# ============================================================
# CLEAN UP EMPTY FOLDERS IN SDCARD
# ============================================================
Log "`n-- Cleanup empty folders --"
Get-ChildItem $src -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending |
    Where-Object { (Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue).Count -eq 0 } |
    ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue; Log "  Removed empty: $($_.FullName)" }

$remaining = Get-ChildItem $src -Force -ErrorAction SilentlyContinue
if ($remaining.Count -eq 0) {
    Remove-Item $src -Force -ErrorAction SilentlyContinue
    Log "  sdcard folder is now EMPTY and removed"
} else {
    Log "  sdcard still has $($remaining.Count) items remaining:"
    $remaining | ForEach-Object {
        $cnt = if ($_.PSIsContainer) { (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue).Count } else { 1 }
        Log "    $($_.Name) ($cnt items)"
    }
}

# ============================================================
# FINAL STRUCTURE REPORT
# ============================================================
Log "`n-- FINAL STRUCTURE --"
Get-ChildItem $dst -Force | Where-Object { $_.PSIsContainer } | Sort-Object Name | ForEach-Object {
    try {
        $c = (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue).Count
        $s = [math]::Round((Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum -ErrorAction SilentlyContinue).Sum / 1GB, 2)
        Log ("  {0,-38} {1,6} files  {2,6} GB" -f $_.Name, $c, $s)
    } catch { }
}

Log "`n================================================"
Log "CLEANUP3 COMPLETE"
Log "================================================"

$script:log | Add-Content "$dst\REORGANIZATION_LOG.txt" -Encoding UTF8
Write-Host "Done. Log appended to $dst\REORGANIZATION_LOG.txt"
