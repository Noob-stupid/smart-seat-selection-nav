$ErrorActionPreference = 'Continue'
$log = 'D:\MAX_xiangmu\.redis-setup\upgrade.log'
function Log($m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $m"
    Write-Host $line
    Add-Content -Path $log -Value $line
}
Set-Content -Path $log -Value '=== upgrade started (elevated) ==='
$dst = 'D:\Redis'
$src = 'D:\MAX_xiangmu\.redis-setup\extracted\Redis-8.10.0-Windows-x64-cygwin-with-Service'

Log '1. stop old Redis service'
sc.exe stop Redis 2>&1 | Out-String | ForEach-Object { Log $_.Trim() }
Start-Sleep -Seconds 3
Get-Process redis-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Log '2. delete old service entry'
sc.exe delete Redis 2>&1 | Out-String | ForEach-Object { Log $_.Trim() }
Start-Sleep -Seconds 2

Log '3. wipe D:\Redis (old leftovers)'
Get-ChildItem $dst -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction Continue
Start-Sleep -Seconds 1

Log '4. copy new package files'
Copy-Item (Join-Path $src '*') $dst -Recurse -Force
$conf = Join-Path $dst 'redis.conf'
(Get-Content $conf) -replace '^logfile ""', 'logfile "D:/Redis/server_log.txt"' | Set-Content $conf
Log 'files in D:\Redis:'
Get-ChildItem $dst | Select-Object -ExpandProperty Name | ForEach-Object { Log "  $_" }

Log '5. install new service via RedisService.exe'
Push-Location $dst
$out = & .\RedisService.exe install -c "$dst\redis.conf" --dir $dst --port 6379 2>&1 | Out-String
Log $out.Trim()
Pop-Location
Start-Sleep -Seconds 2

Log '6. start service'
sc.exe start Redis 2>&1 | Out-String | ForEach-Object { Log $_.Trim() }
Start-Sleep -Seconds 3
sc.exe query Redis 2>&1 | Out-String | ForEach-Object { Log $_.Trim() }
Log '=== upgrade finished ==='
