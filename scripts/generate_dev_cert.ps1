<#
Generates a self-signed TLS certificate for the platform to start with.

Self-signed means every browser warns until it is trusted or replaced - fine
to get encryption running today, not the answer for production. Ask your AD
team for one issued by the internal CA (Certificate Services) once this is
proven out, and just point TLS_CERT_FILE/TLS_KEY_FILE at that instead -
nothing else in the app needs to change.

Requires openssl, which ships with Git for Windows - already a dependency
of app-service.ps1's `git pull` deploys, so it is already on this server.

Usage:
    .\generate_dev_cert.ps1 -Hostname AWGTC-PORTAL-QAS -IpAddress 172.50.35.75
#>
param(
    [Parameter(Mandatory = $true)][string]$Hostname,
    [string]$IpAddress,
    [string]$OutDir = "$PSScriptRoot\..\backend\certs"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
    Write-Host "openssl not found on PATH. It ships with Git for Windows - " `
               "install that, or add its bin folder to PATH, then re-run." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$cert = Join-Path $OutDir "cert.pem"
$key = Join-Path $OutDir "key.pem"

$san = "DNS:$Hostname,DNS:localhost,IP:127.0.0.1"
if ($IpAddress) { $san = "$san,IP:$IpAddress" }

# MSYS_NO_PATHCONV: Git Bash's openssl otherwise mangles the leading "/CN=..."
# in -subj as if it were a Windows path.
$env:MSYS_NO_PATHCONV = "1"
& openssl req -x509 -newkey rsa:2048 -nodes `
    -keyout $key -out $cert -days 825 `
    -subj "/CN=$Hostname" -addext "subjectAltName=$san"

if ($LASTEXITCODE -ne 0) { Write-Host "openssl failed - see above." -ForegroundColor Red; exit 1 }

Write-Host "`nWrote $cert and $key" -ForegroundColor Green
Write-Host "Self-signed: browsers will warn until this is trusted or replaced with a CA-issued certificate."
