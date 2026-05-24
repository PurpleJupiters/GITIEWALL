$DEVICE = "AE6RUT4531003110"
$BACKUP = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$LOG = "E:\SunoMaster\scripts\PushFilesToPhone_Log.txt"
"" | Out-File $LOG -Force

function Log($msg) {
    $line = "[$(Get-Date -f HH:mm:ss)] $msg"
    Write-Host $line
    Add-Content $LOG $line
}

Log "=== Phone File Transfer Started ==="

$folders = @{}
$folders["Photos"] = "/sdcard/Pictures"
$folders["Music Projects"] = "/sdcard/Music Projects"
$folders["Audio"] = "/sdcard/Audio"
$folders["Documents"] = "/sdcard/Documents"
$folders["Video"] = "/sdcard/Video"
$folders["Code"] = "/sdcard/Code"

foreach ($folder in $folders.Keys) {
    $src = "$BACKUP\$folder"
    $dst = $folders[$folder]
    if (!(Test-Path $src)) { Log "SKIP: $folder"; continue }
    Log "Pushing $folder to $dst"
    $files = Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName.Length -lt 220 }
    $pushed = 0
    $skipped = 0
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($src.Length).Replace("\", "/")
        $destPath = $dst + $relative
        $r = adb -s $DEVICE push $file.FullName $destPath 2>&1
        if ($LASTEXITCODE -eq 0) { $pushed++ } else { $skipped++ }
    }
    Log "Done $folder - pushed $pushed skipped $skipped"
}

Log "=== Transfer Complete ==="
