# ============================================================
# RONALD'S PHONE BACKUP - CLEANUP 2
# Handles all remaining sdcard content after main script + Cleanup1
# Uses robocopy for large/deep folder trees (MAX_PATH safe)
# ============================================================

$src  = "E:\Project Backups\HonorPhoneBackup22MAY2026\sdcard"
$dst  = "E:\Project Backups\HonorPhoneBackup22MAY2026"
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
    if ($files.Count -gt 0) { Log "  Moved $($files.Count) [$filter] from $(Split-Path $sourceDir -Leaf) -> $destDir" }
}

function RoboCopyMove($srcDir, $dstDir) {
    if (!(Test-Path $srcDir)) { return }
    EnsureDir $dstDir
    $before = (Get-ChildItem $srcDir -Recurse -File -Force -ErrorAction SilentlyContinue).Count
    robocopy $srcDir $dstDir /E /MOVE /MT:4 /R:1 /W:1 /NP /NFL /NDL 2>&1 | Out-Null
    Log "  Robocopy moved: $srcDir -> $dstDir (exit $LASTEXITCODE, was $before files)"
}

function MoveFolder($sourcePath, $destPath) {
    if (!(Test-Path $sourcePath)) { return }
    # If dest exists, use robocopy to merge, else rename
    if (Test-Path $destPath) {
        RoboCopyMove $sourcePath $destPath
    } else {
        EnsureDir (Split-Path $destPath -Parent)
        try {
            Move-Item $sourcePath -Destination $destPath -Force -EA Stop
            $script:moved++
            Log "  Moved folder: $(Split-Path $sourcePath -Leaf) -> $destPath"
        } catch {
            Log "  MoveFolder fallback to robocopy: $sourcePath"
            RoboCopyMove $sourcePath $destPath
        }
    }
}

Log "CLEANUP2 START"
Log "sdcard source: $src"

# ============================================================
# PICTURES FOLDER - remaining content
# ============================================================
Log "`n-- Pictures cleanup --"
$pics = "$src\Pictures"

# System junk - Gallery cache and thumbnails
RoboCopyMove "$pics\.Gallery2"    "$dst\Ronald's Trash Folder\System Cache\Gallery2"
RoboCopyMove "$pics\.thumbnails"  "$dst\Ronald's Trash Folder\System Cache\Thumbnails"

# Trashed files (phone recycle bin)
$trashedFiles = Get-ChildItem $pics -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -like ".trashed-*" }
if ($trashedFiles) {
    EnsureDir "$dst\Ronald's Trash Folder\Deleted Files\Pictures"
    foreach ($f in $trashedFiles) {
        try { Move-Item $f.FullName -Destination "$dst\Ronald's Trash Folder\Deleted Files\Pictures\" -Force -EA Stop; $script:moved++ }
        catch { $script:errors++ }
    }
    Log "  Moved $($trashedFiles.Count) .trashed files -> Deleted Files\Pictures"
}

# Named Music Project subfolders still in Pictures
foreach ($proj in @("ANARCHY","Dancerz","DUB ME GOOD","Moon Bloom","Underworld Best","VERTIGO","VISCERAL PERCEPTOR")) {
    $projPath = "$pics\$proj"
    if (Test-Path $projPath) {
        MoveFolder $projPath "$dst\Music Projects\$proj\Visuals"
    }
}

# Photo editing app folders
foreach ($app in @("Photoshop Express","PhotoLayers","PhotoResizer","Adobe Express","Segments","inshot")) {
    $appPath = "$pics\$app"
    if (Test-Path $appPath) {
        RoboCopyMove $appPath "$dst\Photos\Photo Editing\$app"
    }
}

# Muck (social media images)
foreach ($muck in @("WhatsApp","Instagram","Facebook","Substack")) {
    $muckPath = "$pics\$muck"
    if (Test-Path $muckPath) {
        RoboCopyMove $muckPath "$dst\Muck\$muck"
    }
}

# Screenshots
RoboCopyMove "$pics\Screenshots"  "$dst\Photos\Screenshots\Apps"

# AI Generated
RoboCopyMove "$pics\Agent WALL Logo" "$dst\Photos\AI Generated\Agent WALL Logo"

# MIDI Sheet Music images
RoboCopyMove "$pics\MidiSheetMusic" "$dst\Audio\Compositions\MIDI\Sheet Music Images"

# Hidden album -> trash
RoboCopyMove "$pics\hiddenAlbum"   "$dst\Ronald's Trash Folder\App Temp\hiddenAlbum"

# Loose image files in Pictures root (pexels, file_*, numbered, etc.)
MoveFiles $pics "*.jpg"  "$dst\Photos\Downloaded Images"
MoveFiles $pics "*.jpeg" "$dst\Photos\Downloaded Images"
MoveFiles $pics "*.png"  "$dst\Photos\Downloaded Images"
MoveFiles $pics "*.webp" "$dst\Photos\Downloaded Images"
MoveFiles $pics "*.mp4"  "$dst\Video\Downloaded"

# Any remaining subfolders -> App Photos
if (Test-Path $pics) {
    Get-ChildItem $pics -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.PSIsContainer) {
            $destSub = "$dst\Photos\App Photos\$($_.Name)"
            RoboCopyMove $_.FullName $destSub
        }
    }
}

# ============================================================
# DOWNLOAD FOLDER - remaining 2792 files (by extension)
# ============================================================
Log "`n-- Download remaining ($((Get-ChildItem "$src\Download" -Recurse -File -Force -ErrorAction SilentlyContinue).Count) files) --"
$dl = "$src\Download"
MoveFiles $dl "*.mp3"   "$dst\Audio\Downloaded Audio\MP3"
MoveFiles $dl "*.wav"   "$dst\Audio\Downloaded Audio\WAV"
MoveFiles $dl "*.m4a"   "$dst\Audio\Downloaded Audio\M4A"
MoveFiles $dl "*.flac"  "$dst\Audio\Downloaded Audio\FLAC"
MoveFiles $dl "*.ogg"   "$dst\Audio\Downloaded Audio\OGG"
MoveFiles $dl "*.mid"   "$dst\Audio\Compositions\MIDI\Other"
MoveFiles $dl "*.midi"  "$dst\Audio\Compositions\MIDI\Other"
MoveFiles $dl "*.mp4"   "$dst\Video\Downloaded"
MoveFiles $dl "*.mkv"   "$dst\Video\Downloaded"
MoveFiles $dl "*.avi"   "$dst\Video\Downloaded"
MoveFiles $dl "*.webm"  "$dst\Video\Downloaded"
MoveFiles $dl "*.jpg"   "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.jpeg"  "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.png"   "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.webp"  "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.gif"   "$dst\Photos\Downloaded Images"
MoveFiles $dl "*.docx"  "$dst\Documents\Word"
MoveFiles $dl "*.doc"   "$dst\Documents\Word"
MoveFiles $dl "*.pdf"   "$dst\Documents\PDF"
MoveFiles $dl "*.txt"   "$dst\Documents\Text"
MoveFiles $dl "*.rtf"   "$dst\Documents\Text"
MoveFiles $dl "*.xlsx"  "$dst\Documents\Spreadsheets\Excel"
MoveFiles $dl "*.csv"   "$dst\Documents\Spreadsheets\CSV"
MoveFiles $dl "*.html"  "$dst\Documents\Web"
MoveFiles $dl "*.htm"   "$dst\Documents\Web"
MoveFiles $dl "*.svg"   "$dst\Documents\Web"
MoveFiles $dl "*.py"    "$dst\Code\Python"
MoveFiles $dl "*.js"    "$dst\Code\JavaScript"
MoveFiles $dl "*.zip"   "$dst\Archives\Download ZIPs"
MoveFiles $dl "*.epub"  "$dst\Documents\eBooks"
MoveFiles $dl "*.tex"   "$dst\Documents\Text"
MoveFiles $dl "*.md"    "$dst\Documents\Text"
MoveFiles $dl "*.json"  "$dst\Code\Projects\SunoMaster"
# Executables -> trash
MoveFiles $dl "*.exe"   "$dst\Ronald's Trash Folder\App Temp\Installers"
MoveFiles $dl "*.apk"   "$dst\Ronald's Trash Folder\App Temp\Installers"
# Dev files
MoveFiles $dl "*.cmake" "$dst\Code\Dev Libraries"
MoveFiles $dl "*.h"     "$dst\Code\Dev Libraries"
MoveFiles $dl "*.so"    "$dst\Code\Dev Libraries"

# Any remaining files in Download
$dlRem = Get-ChildItem $dl -Recurse -File -Force -ErrorAction SilentlyContinue
if ($dlRem.Count -gt 0) {
    EnsureDir "$dst\Archives\Download Misc"
    foreach ($f in $dlRem) {
        try { Move-Item $f.FullName -Destination "$dst\Archives\Download Misc\" -Force -EA Stop; $script:moved++ }
        catch { $script:errors++ }
    }
    Log "  $($dlRem.Count) misc Download files -> Archives\Download Misc"
}

# ============================================================
# LARGE SYSTEM/MEDIA FOLDERS - robocopy
# ============================================================
Log "`n-- Large folders (robocopy) --"
RoboCopyMove "$src\Honor"         "$dst\System - Do Not Touch\Honor App Data"
RoboCopyMove "$src\Movies"        "$dst\Video\Downloaded"
RoboCopyMove "$src\Music"         "$dst\Audio\Music Library"
RoboCopyMove "$src\Sounds"        "$dst\Audio\Sound Libraries\Sounds"
RoboCopyMove "$src\Notifications" "$dst\Audio\Sound Libraries\Notifications"

# ============================================================
# SOUND LIBRARIES that were "moved" but remain
# ============================================================
Log "`n-- Sound Libraries (re-move with robocopy) --"
RoboCopyMove "$src\sound_effects"         "$dst\Audio\Sound Libraries\Sound Effects"
RoboCopyMove "$src\nasa_sounds"           "$dst\Audio\Sound Libraries\NASA"
RoboCopyMove "$src\youtube_sounds"        "$dst\Audio\Sound Libraries\YouTube"
RoboCopyMove "$src\working_sound_effects" "$dst\Audio\Sound Libraries\Working"
RoboCopyMove "$src\test_sounds"           "$dst\Audio\Sound Libraries\Test"
RoboCopyMove "$src\TimidityAE"            "$dst\Audio\Sound Libraries\TimidityAE"

# ============================================================
# VOICE WORK folders
# ============================================================
Log "`n-- Voice Work (re-move with robocopy) --"
RoboCopyMove "$src\VoiceToMidi"   "$dst\Audio\Voice Work\Voice to MIDI"
RoboCopyMove "$src\VoiceToText"   "$dst\Audio\Voice Work\Voice to Text"
RoboCopyMove "$src\Recorder 2026" "$dst\Audio\Voice Work\Voice Memos"

# ============================================================
# CODE / PROJECTS
# ============================================================
Log "`n-- Code Projects (re-move with robocopy) --"
RoboCopyMove "$src\Ronald Pyroid" "$dst\Code\Projects\Ronald Pyroid"
RoboCopyMove "$src\MPA Competition" "$dst\Audio\MPA Competition"

# ============================================================
# SYSTEM FOLDERS
# ============================================================
Log "`n-- System folders --"
RoboCopyMove "$src\HonorSystem"   "$dst\System - Do Not Touch\HonorSystem"
RoboCopyMove "$src\Huawei"        "$dst\System - Do Not Touch\Huawei"
RoboCopyMove "$src\tencent"       "$dst\System - Do Not Touch\tencent"
RoboCopyMove "$src\SystemAndroid" "$dst\System - Do Not Touch\SystemAndroid"
RoboCopyMove "$src\pictorial"     "$dst\System - Do Not Touch\pictorial"
RoboCopyMove "$src\magazine"      "$dst\Ronald's Trash Folder\App Temp\magazine"
RoboCopyMove "$src\Koala"         "$dst\Ronald's Trash Folder\App Temp\Koala"
RoboCopyMove "$src\DownloadHelper" "$dst\Ronald's Trash Folder\App Temp\DownloadHelper"

# sdcard symlink inside sdcard
if (Test-Path "$src\sdcard") {
    try { Remove-Item "$src\sdcard" -Force -Recurse -EA Stop; Log "  Removed sdcard symlink" }
    catch { Log "  Could not remove sdcard\sdcard: $_" }
}

# ============================================================
# MyDocuments (both variants)
# ============================================================
Log "`n-- MyDocuments remaining --"
foreach ($mdName in @(" MyDocuments","MyDocuments")) {
    $mdSrc = "$src\$mdName"
    MoveFiles $mdSrc "*.py"    "$dst\Code\Python"
    MoveFiles $mdSrc "*.mp3"   "$dst\Audio\Downloaded Audio\MP3"
    MoveFiles $mdSrc "*.m4a"   "$dst\Audio\Downloaded Audio\M4A"
    MoveFiles $mdSrc "*.wav"   "$dst\Audio\Downloaded Audio\WAV"
    MoveFiles $mdSrc "*.mp4"   "$dst\Video\Downloaded"
    MoveFiles $mdSrc "*.pdf"   "$dst\Documents\PDF"
    MoveFiles $mdSrc "*.docx"  "$dst\Documents\Word"
    MoveFiles $mdSrc "*.txt"   "$dst\Documents\Text"
    MoveFiles $mdSrc "*.zip"   "$dst\Code\Projects\MyDocuments Archives"
    # Anything left in root
    $rem = Get-ChildItem $mdSrc -File -Force -ErrorAction SilentlyContinue
    if ($rem.Count -gt 0) {
        EnsureDir "$dst\Archives\MyDocuments Misc"
        $rem | ForEach-Object {
            try { Move-Item $_.FullName -Destination "$dst\Archives\MyDocuments Misc\" -Force -EA Stop; $script:moved++ }
            catch { $script:errors++ }
        }
    }
    # Subfolders left
    $subFolders = Get-ChildItem $mdSrc -Directory -Force -ErrorAction SilentlyContinue
    foreach ($sf in $subFolders) {
        RoboCopyMove $sf.FullName "$dst\Archives\MyDocuments\$($sf.Name)"
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
        try { Move-Item $_.FullName -Destination "$dst\Archives\Documents Misc\" -Force -EA Stop; $script:moved++ }
        catch { $script:errors++ }
    }
}

# ============================================================
# CLEAN UP EMPTY FOLDERS IN SDCARD
# ============================================================
Log "`n-- Cleanup empty folders --"
Get-ChildItem $src -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending |
    Where-Object { (Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue).Count -eq 0 } |
    ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }

# Check sdcard itself
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
Log "CLEANUP2 COMPLETE"
Log "  Items moved : $moved"
Log "  Errors      : $errors"
Log "================================================"

$script:log | Add-Content "$dst\REORGANIZATION_LOG.txt" -Encoding UTF8
Write-Host "Done. Log appended to $dst\REORGANIZATION_LOG.txt"
