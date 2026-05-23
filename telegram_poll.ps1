# Telegram Two-Way Bridge — Ronald's Desktop Poller
# Polls bot for new messages with proper offset tracking
# Paste in: PowerShell (on your desktop)

$TOKEN = "8547752402:AAEfMiy2TaliNAEZYgidVCIwDPq5hJGjH2g"
$BASE  = "https://api.telegram.org/bot$TOKEN"
$offset = 0

Write-Host "=== Telegram Poller Running ===" -ForegroundColor Green
Write-Host "Waiting for messages from your phone..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop.`n" -ForegroundColor Yellow

while ($true) {
    try {
        $url  = "$BASE/getUpdates?timeout=20&offset=$offset"
        $resp = Invoke-RestMethod -Uri $url -Method Get -ErrorAction Stop

        foreach ($update in $resp.result) {
            $offset = $update.update_id + 1
            $from   = $update.message.from.first_name
            $text   = $update.message.text
            $time   = (Get-Date).ToString("HH:mm:ss")
            Write-Host "[$time] $from: $text" -ForegroundColor White
        }
    }
    catch {
        Write-Host "Connection error: $_" -ForegroundColor Red
        Start-Sleep -Seconds 5
    }
}
