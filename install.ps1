# Installs clm-harness for the current user on Windows.
#
#   irm https://raw.githubusercontent.com/himax12/clm-harness/main/install.ps1 | iex
#
# It installs uv if it is missing, then installs the harness as a uv tool in its own
# environment with its own Python. Nothing is installed system-wide and no
# administrator rights are needed.
#
# $env:CLM_HARNESS_SOURCE chooses what to install: a path, a git URL, or a PyPI name.
# Run from a checkout, it installs that checkout.

$ErrorActionPreference = 'Stop'
$repo = 'git+https://github.com/himax12/clm-harness'

if ($env:CLM_HARNESS_SOURCE) {
    $source = $env:CLM_HARNESS_SOURCE
} elseif ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml')) -and
          (Select-String -Path (Join-Path $PSScriptRoot 'pyproject.toml') -Pattern '^name = "clm-harness"' -Quiet)) {
    $source = $PSScriptRoot
} else {
    $source = $repo
}

if ($source -like 'git+*' -and -not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is needed to install from $source. Install it with 'winget install Git.Git' and run this again."
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv (https://docs.astral.sh/uv/) ...'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "Installing clm-harness from $source ..."
uv tool install --force --python 3.12 $source
if ($LASTEXITCODE -ne 0) { Write-Error 'uv tool install failed.' }

$bin = (uv tool dir --bin).Trim()
if (($env:Path -split ';') -notcontains $bin) {
    Write-Host ''
    Write-Host "$bin is not on your PATH. Run 'uv tool update-shell' and open a new terminal,"
    Write-Host 'or use the full path below.'
}

Write-Host ''
& (Join-Path $bin 'clm-harness.exe') doctor --offline
Write-Host ''
Write-Host 'Next:'
Write-Host '  clm-harness setup     save your Anthropic API key'
Write-Host '  clm-harness doctor    check everything, including the key'
Write-Host '  clm-harness run "your task" --dir path\to\repo --sandbox docker'
Write-Host ''
Write-Host 'Without Docker, commands run in Git Bash: winget install Git.Git'
# No `exit` here: piped into iex, it would close the user's terminal. Doctor returns 1
# until a key is saved, and that must not make the installer look failed.
$global:LASTEXITCODE = 0
