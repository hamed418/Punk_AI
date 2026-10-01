<#
.SYNOPSIS
    Local SOCKS tunnel so Unacast calls leave from the allowlisted NAT address.

.DESCRIPTION
    Unacast only accepts calls from <NAT_IP> (the Cloud NAT in front of the
    VPC). A laptop is not that address, so local runs route through
    <TUNNEL_VM>: SSH over IAP, dynamic forward on 127.0.0.1:1080, which the
    backend uses via UNACAST_PROXY_URL=socks5://127.0.0.1:1080.

    Starts the VM if it is stopped, checks the egress address, and reconnects
    whenever the IAP relay drops. Leave it running while you test; Ctrl+C quits.

.EXAMPLE
    .\scripts\unacast_tunnel.ps1          # start VM + tunnel
    .\scripts\unacast_tunnel.ps1 -Stop    # stop the VM when you are done
#>
param([switch]$Stop, [int]$Port = 1080, [string]$User = $env:USERNAME.ToLower())

$ErrorActionPreference = 'Stop'
$Project    = '<GCP_PROJECT>'
$Zone       = '<ZONE>'
$Vm         = '<TUNNEL_VM>'
$ExpectedIp = '<NAT_IP>'

if ($Stop) {
    gcloud compute instances stop $Vm --zone=$Zone --project=$Project
    return
}

$status = gcloud compute instances describe $Vm --zone=$Zone --project=$Project --format='value(status)'
if ($status -ne 'RUNNING') {
    Write-Host "Starting $Vm (was $status)..."
    gcloud compute instances start $Vm --zone=$Zone --project=$Project
}
$id  = gcloud compute instances describe $Vm --zone=$Zone --project=$Project --format='value(id)'
$key = Join-Path $HOME '.ssh\google_compute_engine'

# Windows OpenSSH cannot launch gcloud.cmd (or a path with spaces) directly as a
# ProxyCommand, so route it through a tiny wrapper with the absolute path.
$gcloud = (Get-Command gcloud.cmd).Source
$proxy  = Join-Path $env:TEMP 'punk_unacast_iap.cmd'
Set-Content -Path $proxy -Encoding ascii -Value @(
    '@echo off',
    "call `"$gcloud`" compute start-iap-tunnel $Vm %1 --listen-on-stdin --project=$Project --zone=$Zone --verbosity=warning"
)

function Test-Port {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $Port); $true } catch { $false } finally { $c.Close() }
}

if (Test-Port) { throw "127.0.0.1:$Port is already in use - is another tunnel running?" }

$sshArgs = @(
    '-N', '-D', "127.0.0.1:$Port",
    '-i', "`"$key`"",
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'ExitOnForwardFailure=yes',
    '-o', "`"ProxyCommand=$($proxy -replace '\\', '/') %p`"",
    "$User@compute.$id"
) -join ' '

while ($true) {
    $ssh = Start-Process ssh -ArgumentList $sshArgs -NoNewWindow -PassThru
    for ($i = 0; $i -lt 60 -and -not $ssh.HasExited -and -not (Test-Port); $i++) { Start-Sleep 1 }

    if (Test-Port) {
        $ip = (curl.exe -s --max-time 20 --socks5-hostname "127.0.0.1:$Port" https://api.ipify.org)
        if ($ip -eq $ExpectedIp) {
            Write-Host "Tunnel up on 127.0.0.1:$Port - egress $ip (allowlisted)."
        } else {
            Write-Warning "Tunnel up but egress is '$ip', expected $ExpectedIp - Unacast will reject calls."
        }
    }

    $ssh.WaitForExit()
    Write-Warning "Tunnel dropped (ssh exit $($ssh.ExitCode)); reconnecting in 5s. Ctrl+C to quit."
    Start-Sleep 5
}
