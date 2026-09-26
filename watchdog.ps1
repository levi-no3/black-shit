# Watchdog: keeps Discord bot alive. Runs at login via Scheduled Task.
$proj = "C:\Users\leviw\OneDrive\Documents\Default Project"
while ($true) {
    try {
        $running = Get-Process | Where-Object { $_.ProcessName -like "*python*" }
        if (-not $running) {
            Start-Process -FilePath "python" -ArgumentList "-u bot.py" -WorkingDirectory $proj -WindowStyle Hidden
        }
    } catch { }
    Start-Sleep -Seconds 60
}
