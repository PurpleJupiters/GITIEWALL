# PushFilesToPhone.ps1
# Pushes organized folders from PC backup to phone, skipping problem files
# Run in PowerShell (on your desktop)

$DEVICE = "AE6RUT4531003110"
$BACKUP = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$LOG    = "E:\SunoMaster\scripts\PushFilesToPhone_Log.txt"

function Log($msg) {
    $line = "[$(Get-Date -f 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content $LOG $line
}

"" | Out-File $LOG -Force
Log "=== Phone File Transfer Started ==="

$folders = @{
    "Photos"          = "/sdcard/Pictures"
    "Music Projects"  = "/sdcard/Music Projects"
    "Audio"           = "/sdcard/Audio"
    "Documents"       = "/sdcard/Documents"
    "Video"           = "/sdcard/Video"
    "Code"            = "/sdcard/Code"
}

foreach ($folder in $folders.Keys) {
    $src = "$BACKUP\$folder"
    $dst = $folders[$folder]

    if (!(Test-Path $src)) {
        Log "SKIP (not found): $folder"
        continue
    }

    Log "Pushing: $folder -> $dst"

    # Get all files, skip ones with paths over 200 chars
    $files = Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue |
             Where-Object { $_.FullName.Length -lt 220 }

    $skipped = 0
    $pushed  = 0

    foreach ($file in $files) {
        $relative = $file.FullName.Substring($src.Length).Replace("\", "/")
        $destPath = "$dst$relative"

        try {
            $result = adb -s $DEVICE push $file.FullName $destPath 2>&1
            $pushed++
        } catch {
            $skipped++
        }
    }

    Log "Done: $folder — pushed $pushed, skipped $skipped"
}

Log "=== Transfer Complete ==="
Write-Host ""
Write-Host "Log saved to: $LOG" -ForegroundColor Green
