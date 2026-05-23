# ============================================================
# PhoneRestore_Auto.ps1 — Full automated phone restore
# Run in PowerShell (on your desktop) after setup wizard done
# ============================================================

$BACKUP_ROOT = "E:\Project Backups\HonorPhoneBackup22MAY2026"
$TERMUX_BACKUP = "$BACKUP_ROOT\termux_home_backup.tar.gz"
$VLC_APK = "$BACKUP_ROOT\Archives\Download Misc\VLC-Android-3.7.1-arm64.apk"

function Log($msg) { Write-Host "[$(Get-Date -f 'HH:mm:ss')] $msg" -ForegroundColor Cyan }
function OK($msg)  { Write-Host "[$(Get-Date -f 'HH:mm:ss')] OK: $msg" -ForegroundColor Green }
function ERR($msg) { Write-Host "[$(Get-Date -f 'HH:mm:ss')] ERROR: $msg" -ForegroundColor Red }

# ── Wait for phone ──────────────────────────────────────────
Log "Waiting for phone to connect via ADB..."
$device = $null
while (-not $device) {
    $devices = adb devices | Select-String "device$"
    if ($devices) { $device = ($devices -split "\s+")[0]; break }
    Start-Sleep -Seconds 3
}
OK "Phone connected: $device"

# ── Enable ADB over WiFi (optional, helps if USB disconnects) ─
Log "Setting up ADB..."
adb -s $device shell settings put global adb_enabled 1 2>$null

# ── Install VLC ──────────────────────────────────────────────
if (Test-Path $VLC_APK) {
    Log "Installing VLC..."
    $result = adb -s $device install -r $VLC_APK 2>&1
    if ($result -match "Success") { OK "VLC installed" }
    else { ERR "VLC install failed: $result" }
} else {
    ERR "VLC APK not found at: $VLC_APK"
}

# ── Push Termux backup ───────────────────────────────────────
Log "Pushing Termux backup to phone (175MB — takes ~15 sec)..."
adb -s $device push $TERMUX_BACKUP /sdcard/termux_home_backup.tar.gz
OK "Termux backup pushed to /sdcard/"

# ── Done — Termux extract must be done inside Termux ────────
Write-Host ""
Write-Host "=================================================" -ForegroundColor Yellow
Write-Host " MANUAL STEP REQUIRED — Do this on your phone:" -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host " 1. Install Termux from F-Droid (NOT Play Store)" -ForegroundColor White
Write-Host "    https://f-droid.org/packages/com.termux/" -ForegroundColor Gray
Write-Host ""
Write-Host " 2. Open Termux and run this command:" -ForegroundColor White
Write-Host ""
Write-Host "    tar -xzf /sdcard/termux_home_backup.tar.gz -C /data/data/com.termux/files/" -ForegroundColor Green
Write-Host ""
Write-Host " 3. Then restart Termux — all your files will be back" -ForegroundColor White
Write-Host ""
Write-Host "=================================================" -ForegroundColor Yellow
OK "All automated steps complete!"
