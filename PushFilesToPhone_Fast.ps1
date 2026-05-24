$DEVICE = "AE6RUT4531003110"
$BACKUP = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$LOG = "E:\SunoMaster\scripts\PushFast_Log.txt"
"" | Out-File $LOG -Force

function Log($msg) {
    $line = "[$(Get-Date -f HH:mm:ss)] $msg"
    Write-Host $line
    Add-Content $LOG $line
}

Log "=== Fast Phone File Transfer Started ==="

$folders = @{}
$folders["Photos"] = "/sdcard/Pictures"
$folders["Music Projects"] = "/sdcard/MusicProjects"
$folders["Audio"] = "/sdcard/Audio"
$folders["Documents"] = "/sdcard/Documents"
$folders["Video"] = "/sdcard/Video"
$folders["Code"] = "/sdcard/Code"

foreach ($folder in $folders.Keys) {
    $src = "$BACKUP\$folder"
    $dst = $folders[$folder]
    if (!(Test-Path $src)) { Log "SKIP: $folder"; continue }
    Log "Pushing $folder..."
    adb -s $DEVICE push $src $dst 2>&1 | Select-String -Pattern "pushed|error|failed" | ForEach-Object { Log $_ }
    Log "Done: $folder"
}

Log "=== All Done ==="
