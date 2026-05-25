Add-Type -Assembly PresentationCore
$clip = [Windows.Clipboard]::GetText()
if ($clip -and $clip.TrimStart().StartsWith('[')) {
    $clip | Out-File -FilePath "C:\Users\equat\Downloads\tiktok_cookies.json" -Encoding utf8 -NoNewline
    Write-Host "Saved! $(($clip | ConvertFrom-Json).Count) cookies written to Downloads\tiktok_cookies.json" -ForegroundColor Green
} else {
    Write-Host "Clipboard doesn't look like cookie JSON. Did you click Export in Cookie-Editor first?" -ForegroundColor Red
}
