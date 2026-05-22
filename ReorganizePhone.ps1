# ============================================================
# RONALD'S PHONE BACKUP REORGANIZATION SCRIPT
# Source : E:\Project Backups\HonorPhoneBackup22MAY2026\sdcard
# Target : E:\Project Backups\HonorPhoneBackup22MAY2026\
# Date   : 22 MAY 2026
# ============================================================

$src = "E:\Project Backups\HonorPhoneBackup22MAY2026\sdcard"
$dst = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$logLines = [System.Collections.Generic.List[string]]::new()
$moved = 0
$errors = 0

function Log($msg) {
    $script:logLines.Add("$(Get-Date -f 'HH:mm:ss')  $msg")
    Write-Host $msg
}

function Dir($path) {
    if (!(Test-Path $path)) {
        New-Item -ItemType Directory -Force $path | Out-Null
    }
}

function MoveFiles($sourceDir, $filter, $destDir) {
    if (!(Test-Path $sourceDir)) { return }
    Dir $destDir
    $files = Get-ChildItem $sourceDir -Filter $filter -File -Force -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        try {
            Move-Item $f.FullName -Destination $destDir -Force -ErrorAction Stop
            $script:moved++
        } catch {
            Log "  ERROR: $($f.FullName) -$_"
            $script:errors++
        }
    }
    if ($files.Count -gt 0) { Log "  Moved $($files.Count) [$filter] -> $destDir" }
}

function MoveFolder($sourcePath, $destPath) {
    if (!(Test-Path $sourcePath)) { return }
    Dir (Split-Path $destPath -Parent)
    try {
        Move-Item $sourcePath -Destination $destPath -Force -ErrorAction Stop
        $script:moved++
        Log "  Moved folder: $(Split-Path $sourcePath -Leaf) ->$destPath"
    } catch {
        Log "  ERROR moving folder $sourcePath -$_"
        $script:errors++
    }
}

function MoveFolderContents($sourceDir, $destDir) {
    if (!(Test-Path $sourceDir)) { return }
    Dir $destDir
    $items = Get-ChildItem $sourceDir -Force -ErrorAction SilentlyContinue
    foreach ($item in $items) {
        try {
            Move-Item $item.FullName -Destination $destDir -Force -ErrorAction Stop
            $script:moved++
        } catch {
            Log "  ERROR: $($item.FullName) -$_"
            $script:errors++
        }
    }
    if ($items.Count -gt 0) { Log "  Moved $($items.Count) items from $(Split-Path $sourceDir -Leaf) ->$destDir" }
}

# ------ PRE-COUNT ------------------------------------------------------------------------------------------------------------------------------------------------
$beforeCount = (Get-ChildItem $src -Recurse -File -Force -ErrorAction SilentlyContinue).Count
$beforeSize  = (Get-ChildItem $src -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
Log "START -$beforeCount files, $([math]::Round($beforeSize/1GB,2)) GB in source"

# ============================================================
# 1. PHOTOS
# ============================================================
Log "`n------ PHOTOS ------------------------------------------------------------------------------------------------------------------"

# Camera -sort by year from filename, fallback to file date
Log "  Sorting camera photos by year..."
$camSrc = "$src\DCIM\Camera"
if (Test-Path $camSrc) {
    Get-ChildItem $camSrc -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $year = $null
        if ($_.Name -match '^(20\d{2})') { $year = $matches[1] }
        elseif ($_.Name -match '^(IMG_|VID_|lv_|MAMA|Lois|Wann|AAAA|Anar)') { $year = $_.LastWriteTime.Year.ToString() }
        elseif ($_.Name -match '^\.tra') { $year = "Unsorted" }
        elseif ($_.Name -match '^water') { $year = "Watermarked" }
        else { $year = $_.LastWriteTime.Year.ToString() }
        $yearDir = "$dst\Photos\Camera\$year"
        Dir $yearDir
        try { Move-Item $_.FullName -Destination $yearDir -Force -ErrorAction Stop; $script:moved++ }
        catch { Log "  ERROR: $($_.FullName)"; $script:errors++ }
    }
    Log "  Camera photos sorted by year"
}

# DCIM subfolders
MoveFolder "$src\DCIM\Screenshots"   "$dst\Photos\Screenshots\Phone"
MoveFolder "$src\DCIM\PlantNet"      "$dst\Photos\Plants"
MoveFolder "$src\DCIM\Partner"       "$dst\Photos\Camera\Partner"
MoveFolder "$src\DCIM\Facebook"      "$dst\Muck\Facebook"
MoveFolder "$src\DCIM\CapCut"        "$dst\Video\CapCut"

# Pictures subfolders
MoveFolder "$src\Pictures\Screenshots"        "$dst\Photos\Screenshots\Apps"
MoveFolder "$src\Pictures\Photoshop Express"  "$dst\Photos\Photo Editing\Photoshop Express"
MoveFolder "$src\Pictures\PhotoLayers"        "$dst\Photos\Photo Editing\PhotoLayers"
MoveFolder "$src\Pictures\Adobe Express"      "$dst\Photos\Photo Editing\Adobe Express"
MoveFolder "$src\Pictures\Segments"           "$dst\Photos\Photo Editing\Segments"
MoveFolder "$src\Pictures\inshot"             "$dst\Photos\Photo Editing\InShot"
MoveFolder "$src\Pictures\PhotoResizer"       "$dst\Photos\Photo Editing\PhotoResizer"
MoveFolder "$src\Pictures\Koala"              "$dst\Photos\AI Generated"
MoveFolder "$src\Pictures\Agent WALL Logo"    "$dst\Photos\AI Generated"

# Music project visuals
MoveFolder "$src\Pictures\ANARCHY"            "$dst\Music Projects\ANARCHY\Visuals"
MoveFolder "$src\Pictures\Dancerz"            "$dst\Music Projects\Dancerz\Visuals"
MoveFolder "$src\Pictures\DUB ME GOOD"        "$dst\Music Projects\DUB ME GOOD\Visuals"
MoveFolder "$src\Pictures\Moon Bloom"         "$dst\Music Projects\Moon Bloom\Visuals"
MoveFolder "$src\Pictures\Underworld Best"    "$dst\Music Projects\Underworld Best\Visuals"
MoveFolder "$src\Pictures\VERTIGO"            "$dst\Music Projects\VERTIGO\Visuals"
MoveFolder "$src\Pictures\VISCERAL PERCEPTOR" "$dst\Music Projects\VISCERAL PERCEPTOR\Visuals"

# Muck -social media chat images
MoveFolder "$src\Pictures\WhatsApp"   "$dst\Muck\WhatsApp"
MoveFolder "$src\Pictures\Instagram"  "$dst\Muck\Instagram"
MoveFolder "$src\Pictures\Messenger"  "$dst\Muck\Messenger"
MoveFolder "$src\Pictures\WeChat"     "$dst\Muck\WeChat"
MoveFolder "$src\Pictures\Substack"   "$dst\Muck\Substack"

# MIDI sheet music images
MoveFolder "$src\Pictures\MidiSheetMusic"     "$dst\Audio\Compositions\MIDI\Sheet Music Images"

# Photo editing misc
MoveFolder "$src\Pictures\VideoEditor"        "$dst\Photos\Photo Editing\VideoEditor"
MoveFolder "$src\Pictures\History-PhotoLayers" "$dst\Ronald's Trash Folder\App Temp\History-PhotoLayers"
MoveFolder "$src\Pictures\hiddenAlbum"        "$dst\Ronald's Trash Folder\App Temp\hiddenAlbum"
MoveFolder "$src\Pictures\DUB ME GOOD"        "$dst\Music Projects\DUB ME GOOD\Visuals"

# Trash -system cache
MoveFolder "$src\Pictures\.Gallery2"    "$dst\Ronald's Trash Folder\System Cache\Gallery2"
MoveFolder "$src\Pictures\.thumbnails"  "$dst\Ronald's Trash Folder\System Cache\Thumbnails"
MoveFolder "$src\Pictures\Facebook"     "$dst\Muck\Facebook Photos"

# Shared photos
MoveFolderContents "$src\.photoShare"   "$dst\Photos\Shared"
MoveFolder         "$src\HONOR Share"   "$dst\Photos\Shared\HONOR Share"

# ============================================================
# 2. AUDIO -COMPOSITIONS (loose files at sdcard root)
# ============================================================
Log "`n------ AUDIO COMPOSITIONS ------------------------------------------------------------------------------"

# MIDI -Fractal Series
foreach ($f in @("Fractal_Composition_MIDI.mid","fractal_composition.mid","Fractal_Enhanced_Piano.mid","Fractal_Evolving_Modes.mid","Fractal_Masterpiece.mid")) {
    if (Test-Path "$src\$f") { Dir "$dst\Audio\Compositions\MIDI\Fractal Series"; Move-Item "$src\$f" "$dst\Audio\Compositions\MIDI\Fractal Series\" -Force; $script:moved++ }
}
Log "  MIDI Fractal Series moved"

# MIDI -Techno Series
foreach ($f in @("techno_audionodes_ready.mid","techno_exact_4min.mid","techno_explicit_4min.mid","techno_final_4minutes.mid","techno_final_5minutes.mid","techno_full_4min.mid")) {
    if (Test-Path "$src\$f") { Dir "$dst\Audio\Compositions\MIDI\Techno Series"; Move-Item "$src\$f" "$dst\Audio\Compositions\MIDI\Techno Series\" -Force; $script:moved++ }
}
Log "  MIDI Techno Series moved"

# MIDI -Entropy Series
foreach ($f in @("entropy_jazz_5part.mid","entropy_jazz_fixed.mid","grid_entropy_song.mid")) {
    if (Test-Path "$src\$f") { Dir "$dst\Audio\Compositions\MIDI\Entropy Series"; Move-Item "$src\$f" "$dst\Audio\Compositions\MIDI\Entropy Series\" -Force; $script:moved++ }
}
Log "  MIDI Entropy Series moved"

# MIDI -Underworld Series
foreach ($f in @("underworld_phrygian_techno.mid")) {
    if (Test-Path "$src\$f") { Dir "$dst\Audio\Compositions\MIDI\Underworld Series"; Move-Item "$src\$f" "$dst\Audio\Compositions\MIDI\Underworld Series\" -Force; $script:moved++ }
}

# WAV -Underworld Series
foreach ($f in @("underworld_final_song.wav","underworld_force_spyder_mix.wav","underworld_fractals.wav","underworld_fractals_extended.wav","complex_underworld_song.wav")) {
    if (Test-Path "$src\$f") { Dir "$dst\Audio\Compositions\WAV\Underworld Series"; Move-Item "$src\$f" "$dst\Audio\Compositions\WAV\Underworld Series\" -Force; $script:moved++ }
}
Log "  WAV Underworld Series moved"

# WAV -Other
foreach ($f in @("my_childrens_smile_reimagined.wav")) {
    if (Test-Path "$src\$f") { Dir "$dst\Audio\Compositions\WAV\Other"; Move-Item "$src\$f" "$dst\Audio\Compositions\WAV\Other\" -Force; $script:moved++ }
}

# VoiceToMidi folder
MoveFolder "$src\VoiceToMidi"    "$dst\Audio\Voice Work\Voice to MIDI"
MoveFolder "$src\VoiceToText"    "$dst\Audio\Voice Work\Voice to Text"
MoveFolder "$src\Recorder 2026"  "$dst\Audio\Voice Work\Voice Memos"
MoveFolder "$src\Recordings"     "$dst\Audio\Voice Work\Other Recordings"

# Sounds folder (M4A recordings)
MoveFiles "$src\Sounds" "*.m4a" "$dst\Audio\Recordings\M4A"
MoveFiles "$src\Sounds" "*.amr" "$dst\Audio\Recordings\AMR"
MoveFiles "$src\Sounds" "*.jpg" "$dst\Ronald's Trash Folder\App Temp\SoundCovers"
MoveFiles "$src\Sounds" "*.txt" "$dst\Audio\Recordings\M4A"

# Music Library
MoveFiles "$src\Music" "*.mp3"  "$dst\Audio\Music Library\MP3"
MoveFiles "$src\Music" "*.m4a"  "$dst\Audio\Music Library\M4A"
MoveFiles "$src\Music" "*.docx" "$dst\Documents\Word"
MoveFiles "$src\Music" "*.jpg"  "$dst\Ronald's Trash Folder\App Temp\MusicCovers"

# MPA Competition
MoveFolder "$src\MPA Competition" "$dst\Audio\MPA Competition"

# Sound Libraries
MoveFolder "$src\sound_effects"          "$dst\Audio\Sound Libraries\Sound Effects"
MoveFolder "$src\nasa_sounds"            "$dst\Audio\Sound Libraries\NASA"
MoveFolder "$src\youtube_sounds"         "$dst\Audio\Sound Libraries\YouTube"
MoveFolder "$src\verified_sounds"        "$dst\Audio\Sound Libraries\Verified"
MoveFolder "$src\verified_sounds_bundle" "$dst\Audio\Sound Libraries\Verified Bundle"
MoveFolder "$src\working_sound_effects"  "$dst\Audio\Sound Libraries\Working"
MoveFolder "$src\test_sounds"            "$dst\Audio\Sound Libraries\Test"
MoveFolder "$src\youtube_webm_audio"     "$dst\Audio\Sound Libraries\YouTube WebM"
MoveFolder "$src\TimidityAE"             "$dst\Audio\Sound Libraries\TimidityAE"

# Ronald Pyroid MIDI
MoveFiles "$src\Ronald Pyroid" "*.mid" "$dst\Audio\Compositions\MIDI\Other"
MoveFiles "$src\Ronald Pyroid" "*.py"  "$dst\Code\Python"

# ============================================================
# 3. VIDEO
# ============================================================
Log "`n------ VIDEO ------------------------------------------------------------------------------------------------------------------------"
MoveFolder "$src\Movies" "$dst\Video\Downloaded"

# Camera videos -sort by year
$camSrc = "$src\DCIM\Camera"
if (Test-Path $camSrc) {
    Get-ChildItem $camSrc -Filter "*.mp4" -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $year = $_.LastWriteTime.Year.ToString()
        $yearDir = "$dst\Video\Camera\$year"
        Dir $yearDir
        try { Move-Item $_.FullName -Destination $yearDir -Force -ErrorAction Stop; $script:moved++ }
        catch { $script:errors++ }
    }
    Log "  Camera videos sorted by year"
}

# ============================================================
# 4. DOCUMENTS (from Download folder)
# ============================================================
Log "`n------ DOCUMENTS ---------------------------------------------------------------------------------------------------------"
MoveFiles "$src\Download" "*.docx" "$dst\Documents\Word"
MoveFiles "$src\Download" "*.doc"  "$dst\Documents\Word"
MoveFiles "$src\Download" "*.pdf"  "$dst\Documents\PDF"
MoveFiles "$src\Download" "*.xlsx" "$dst\Documents\Spreadsheets\Excel"
MoveFiles "$src\Download" "*.xls"  "$dst\Documents\Spreadsheets\Excel"
MoveFiles "$src\Download" "*.csv"  "$dst\Documents\Spreadsheets\CSV"
MoveFiles "$src\Download" "*.txt"  "$dst\Documents\Text"
MoveFiles "$src\Download" "*.rtx"  "$dst\Documents\Text"
MoveFiles "$src\Download" "*.html" "$dst\Documents\Web"
MoveFiles "$src\Download" "*.svg"  "$dst\Documents\Web"

# topics.txt from root
if (Test-Path "$src\topics.txt") {
    Dir "$dst\Documents\Text"
    Move-Item "$src\topics.txt" "$dst\Documents\Text\" -Force; $script:moved++
    Log "  topics.txt moved"
}

# combinations.jsonl ->Code/Projects/SunoMaster
if (Test-Path "$src\combinations.jsonl") {
    Dir "$dst\Code\Projects\SunoMaster"
    Move-Item "$src\combinations.jsonl" "$dst\Code\Projects\SunoMaster\" -Force; $script:moved++
    Log "  combinations.jsonl ->Code/Projects/SunoMaster"
}

# MyDocuments -dev files
MoveFiles "$src\ MyDocuments" "*.cmake" "$dst\Code\Dev Libraries"
MoveFiles "$src\ MyDocuments" "*.pc"    "$dst\Code\Dev Libraries"
MoveFiles "$src\ MyDocuments" "*.so"    "$dst\Code\Dev Libraries"
MoveFiles "$src\ MyDocuments" "*.h"     "$dst\Code\Dev Libraries"
MoveFiles "$src\ MyDocuments" "*.zip"   "$dst\Code\Projects\MyDocuments Archives"
MoveFiles "$src\ MyDocuments" "*.pdf"   "$dst\Documents\PDF"
MoveFiles "$src\ MyDocuments" "*.mp3"   "$dst\Audio\Downloaded Audio\MP3"
MoveFiles "$src\ MyDocuments" "*.m4a"   "$dst\Audio\Downloaded Audio\M4A"
MoveFiles "$src\ MyDocuments" "*.mp4"   "$dst\Video\Downloaded"
MoveFiles "$src\ MyDocuments" "*.wav"   "$dst\Audio\Downloaded Audio\WAV"

# ============================================================
# 5. AUDIO DOWNLOADS (from Download folder)
# ============================================================
Log "`n------ AUDIO DOWNLOADS ---------------------------------------------------------------------------------------"
MoveFiles "$src\Download" "*.mp3" "$dst\Audio\Downloaded Audio\MP3"
MoveFiles "$src\Download" "*.wav" "$dst\Audio\Downloaded Audio\WAV"
MoveFiles "$src\Download" "*.m4a" "$dst\Audio\Downloaded Audio\M4A"
MoveFiles "$src\Download" "*.mid" "$dst\Audio\Compositions\MIDI\Other"
MoveFiles "$src\Download" "*.webm" "$dst\Audio\Downloaded Audio\WebM"

# ============================================================
# 6. IMAGES FROM DOWNLOAD
# ============================================================
Log "`n------ IMAGES FROM DOWNLOAD ------------------------------------------------------------------------"
MoveFiles "$src\Download" "*.jpg"  "$dst\Photos\Downloaded Images"
MoveFiles "$src\Download" "*.jpeg" "$dst\Photos\Downloaded Images"
MoveFiles "$src\Download" "*.png"  "$dst\Photos\Downloaded Images"
MoveFiles "$src\Download" "*.webp" "$dst\Photos\Downloaded Images"

# ============================================================
# 7. VIDEO FROM DOWNLOAD
# ============================================================
MoveFiles "$src\Download" "*.mp4" "$dst\Video\Downloaded"

# ============================================================
# 8. CODE
# ============================================================
Log "`n------ CODE ---------------------------------------------------------------------------------------------------------------------------"
MoveFiles "$src\Download" "*.py"  "$dst\Code\Python"
MoveFolder "$src\Download\wetransfer_source-code-pack_2025-08-29_2355" "$dst\Code\Projects\WeTransfer Source Pack"
MoveFolder "$src\Ronald Pyroid" "$dst\Code\Projects\Ronald Pyroid"

# ============================================================
# 9. ARCHIVES (remaining ZIPs from Download)
# ============================================================
Log "`n------ ARCHIVES ---------------------------------------------------------------------------------------------------------------"
MoveFiles "$src\Download" "*.zip" "$dst\Archives"

# ============================================================
# 10. RONALD'S TRASH FOLDER
# ============================================================
Log "`n------ RONALD'S TRASH FOLDER ---------------------------------------------------------------------"

# Duplicate ZIP bundles
foreach ($f in @("youtube_sounds_bundle.zip","youtube_webm_audio_bundle.zip","combinationszipped.zip","nasa_sounds_bundle.zip","verified_sounds_bundle.zip","working_sound_effects_bundle.zip","sound_effects_bundle.zip")) {
    if (Test-Path "$src\$f") {
        Dir "$dst\Ronald's Trash Folder\Duplicate ZIPs"
        Move-Item "$src\$f" "$dst\Ronald's Trash Folder\Duplicate ZIPs\" -Force; $script:moved++
    }
}
Log "  Duplicate ZIPs moved"

# Deleted files bin
MoveFolder "$src\.File_Recycle"  "$dst\Ronald's Trash Folder\Deleted Files"

# System cache / app temp
MoveFolder "$src\.archivetemp"   "$dst\Ronald's Trash Folder\App Temp\.archivetemp"
MoveFolder "$src\.fileMOShare"   "$dst\Ronald's Trash Folder\App Temp\.fileMOShare"
MoveFolder "$src\.mixplorer"     "$dst\Ronald's Trash Folder\App Temp\.mixplorer"
MoveFolder "$src\magicLinkDemo"  "$dst\Ronald's Trash Folder\App Temp\magicLinkDemo"
MoveFolder "$src\Saved Searches" "$dst\Ronald's Trash Folder\App Temp\Saved Searches"
MoveFolder "$src\sdcard"         "$dst\Ronald's Trash Folder\App Temp\sdcard symlink"

# Empty folders
foreach ($f in @("Alarms","Ringtones","Podcasts","Audiobooks")) {
    if (Test-Path "$src\$f") {
        Dir "$dst\Ronald's Trash Folder\Empty Folders"
        Move-Item "$src\$f" "$dst\Ronald's Trash Folder\Empty Folders\" -Force
    }
}
Log "  Empty folders moved"

# ============================================================
# 11. SYSTEM -DO NOT TOUCH
# ============================================================
Log "`n------ SYSTEM -DO NOT TOUCH ---------------------------------------------------------------------"
MoveFolder "$src\Android"       "$dst\System - Do Not Touch\Android"
MoveFolder "$src\HonorSystem"   "$dst\System - Do Not Touch\HonorSystem"
MoveFolder "$src\Huawei"        "$dst\System - Do Not Touch\Huawei"
MoveFolder "$src\tencent"       "$dst\System - Do Not Touch\tencent"
MoveFolder "$src\backup"        "$dst\System - Do Not Touch\backup"
MoveFolder "$src\SystemAndroid" "$dst\System - Do Not Touch\SystemAndroid"
MoveFolder "$src\storage"       "$dst\System - Do Not Touch\storage"
MoveFolder "$src\Honor"         "$dst\System - Do Not Touch\Honor App Data"
MoveFolder "$src\AllRecovery"   "$dst\System - Do Not Touch\AllRecovery"
MoveFolder "$src\magazine"      "$dst\System - Do Not Touch\magazine"
MoveFolder "$src\Huawei"        "$dst\System - Do Not Touch\Huawei"
MoveFolder "$src\Koala"         "$dst\Photos\AI Generated\Koala App"
MoveFolder "$src\DownloadHelper" "$dst\Ronald's Trash Folder\App Temp\DownloadHelper"
MoveFolder "$src\pictorial"     "$dst\System - Do Not Touch\pictorial"

# ============================================================
# 12. ANYTHING REMAINING IN DOWNLOAD
# ============================================================
Log "`n------ REMAINING DOWNLOAD FILES ------------------------------------------------------------"
if (Test-Path "$src\Download") {
    $remaining = Get-ChildItem "$src\Download" -File -Force -ErrorAction SilentlyContinue
    if ($remaining.Count -gt 0) {
        Dir "$dst\Archives\Download Misc"
        $remaining | ForEach-Object {
            try { Move-Item $_.FullName -Destination "$dst\Archives\Download Misc\" -Force; $script:moved++ }
            catch { $script:errors++ }
        }
        Log "  $($remaining.Count) misc Download files ->Archives\Download Misc"
    }
}

# ============================================================
# 13. REMOVE EMPTY FOLDERS FROM SRC
# ============================================================
Log "`n------ CLEANUP EMPTY FOLDERS ---------------------------------------------------------------------"
Get-ChildItem $src -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending |
    Where-Object { (Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue).Count -eq 0 } |
    ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
Log "  Empty folders removed"

# ============================================================
# 14. POST-COUNT & LOG
# ============================================================
$afterCount = (Get-ChildItem $dst -Recurse -File -Force -ErrorAction SilentlyContinue).Count
$afterSize  = (Get-ChildItem $dst -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum

Log "`n================================================"
Log "COMPLETE"
Log "  Items moved   : $moved"
Log "  Errors        : $errors"
Log "  Files before  : $beforeCount"
Log "  Files after   : $afterCount"
Log "  Size before   : $([math]::Round($beforeSize/1GB,2)) GB"
Log "  Size after    : $([math]::Round($afterSize/1GB,2)) GB"
Log "================================================"

# Save log to file
$logPath = "$dst\REORGANIZATION_LOG.txt"
$logLines | Out-File $logPath -Encoding UTF8
Write-Host "`nLog saved to: $logPath"
