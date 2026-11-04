<#
  ComfyUI-SeeThrough-Easy: one-step Windows installer.

  Installs a portable ComfyUI that matches the graphics card (Nvidia or AMD),
  adds the SeeThrough nodes, downloads the models, and puts a "SeeThrough"
  shortcut on the desktop. Nothing is installed system-wide except, if it is
  missing, Microsoft's Visual C++ runtime (Windows asks for permission).

  Run it again any time to update the SeeThrough nodes or to finish an
  interrupted install; finished steps are skipped.

  Usage (PowerShell):
    irm https://raw.githubusercontent.com/FREES0L/ComfyUI-SeeThrough-Easy/master/windows/install.ps1 | iex

  Options, when run as a file:
    -InstallDir C:\SeeThrough   where everything goes (default C:\SeeThrough)
    -Gpu auto|nvidia|nvidia_cu126|amd|intel   override the graphics card detection
    -SkipModels                 do not download the ~13 GB of models now (first run will)
    -NoShortcut                 no desktop shortcut
    -NodeSource <folder>        install the nodes from a local folder instead of GitHub
    -ComfyVersion v0.44.0       ComfyUI release to install
#>
param(
    [string]$InstallDir = "C:\SeeThrough",
    [ValidateSet("auto", "nvidia", "nvidia_cu126", "amd", "intel")]
    [string]$Gpu = "auto",
    [switch]$SkipModels,
    [switch]$NoShortcut,
    [string]$NodeSource = "",
    [string]$ComfyVersion = "v0.44.0",
    [string]$Repo = "FREES0L/ComfyUI-SeeThrough-Easy",
    [string]$Branch = "master"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar on
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$NodeName = "ComfyUI-SeeThrough-Easy"

function Say($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Info($msg) { Write-Host "    $msg" }
function Warn($msg) { Write-Host "    WARNING: $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host ""
    Write-Host "STOPPED: $msg" -ForegroundColor Red
    Write-Host "Nothing is broken; fix the problem above and run the installer again." -ForegroundColor Red
    throw "SeeThrough install stopped: $msg"
}

# Run a native program. Windows PowerShell 5.1 can turn anything a program writes to
# stderr (curl's progress bar, pip's warnings) into a terminating error while
# $ErrorActionPreference is Stop, so relax it for the call and check $LASTEXITCODE instead.
function Native([scriptblock]$block) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $block } finally { $ErrorActionPreference = $old }
}

function Download($url, $dest) {
    # curl.exe ships with Windows 10 1803+; it shows progress, follows redirects and resumes.
    $tmp = "$dest.part"
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    if (Test-Path $curl) {
        Native { & $curl -L --fail --retry 5 --retry-delay 5 -C - -o $tmp $url }
        if ($LASTEXITCODE -ne 0) {
            # a stale .part can make resume fail (e.g. after the file on the server changed); retry from scratch once
            Remove-Item -Force -ErrorAction SilentlyContinue $tmp
            Native { & $curl -L --fail --retry 5 --retry-delay 5 -o $tmp $url }
            if ($LASTEXITCODE -ne 0) { Fail "Download failed: $url" }
        }
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tmp
    }
    Move-Item -Force $tmp $dest
}

Write-Host ""
Write-Host "  SeeThrough for ComfyUI - installer" -ForegroundColor Green
Write-Host "  Splits an anime character picture into separate layers."
Write-Host "  Install folder: $InstallDir"

# ---------------------------------------------------------------- checks
Say "Checking this computer"
if (-not [Environment]::Is64BitOperatingSystem) { Fail "This needs 64-bit Windows." }

$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Info "Memory (RAM): $ramGB GB"
if ($ramGB -lt 16) { Warn "Less than 16 GB of RAM. The models need about 11 GB of RAM while running; this will likely be very slow or fail." }
elseif ($ramGB -lt 24) { Warn "16 GB of RAM works but is tight; close other big programs (browsers with many tabs, games) while it runs." }

$drive = (Split-Path -Qualifier $InstallDir)
$free = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$drive'").FreeSpace
if ($null -eq $free) { Fail "Drive $drive was not found. Pick another folder with -InstallDir." }
$freeGB = [math]::Round($free / 1GB)
Info "Free space on ${drive}: $freeGB GB"
$alreadyThere = Test-Path (Join-Path $InstallDir "ComfyUI_windows_portable\python_embeded\python.exe")
$needGB = 30
if ($SkipModels) { $needGB = 14 }
if ($alreadyThere) { $needGB = 0 }
if (-not $SkipModels -and $alreadyThere) { $needGB = 14 }
if ($freeGB -lt $needGB) { Fail "Needs about $needGB GB free on $drive (ComfyUI ~8 GB, models ~13 GB, plus room to unpack)." }

# ---------------------------------------------------------------- graphics card
$cards = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
foreach ($c in $cards) { Info "Graphics: $c" }
$vramGB = 0
if ($Gpu -eq "auto") {
    $nv = $cards | Where-Object { $_ -match "NVIDIA" } | Select-Object -First 1
    $amd = $cards | Where-Object { $_ -match "AMD|Radeon" } | Select-Object -First 1
    $intel = $cards | Where-Object { $_ -match "Arc" } | Select-Object -First 1
    if ($nv) { $Gpu = "nvidia" }
    elseif ($amd) { $Gpu = "amd" }
    elseif ($intel) { $Gpu = "intel" }
    else { Fail "No Nvidia, AMD or Intel Arc graphics card found. See-through needs a graphics card with 8 GB or more." }
}

if ($Gpu -like "nvidia*") {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) {
        $q = Native { & nvidia-smi --query-gpu=driver_version,memory.total --format=csv,noheader,nounits } | Select-Object -First 1
        $parts = $q -split ","
        $driver = $parts[0].Trim()
        $vramGB = [math]::Round([double]$parts[1].Trim() / 1024)
        Info "Nvidia driver $driver, $vramGB GB of video memory"
        $major = [int]($driver -split "\.")[0]
        if ($Gpu -eq "nvidia" -and $major -lt 580) {
            Info "Driver is older than 580, using the CUDA 12.6 build of ComfyUI (works with older drivers)."
            $Gpu = "nvidia_cu126"
        }
        if ($major -lt 560) { Warn "Your Nvidia driver is old ($driver). If ComfyUI fails to start, update it from nvidia.com/drivers." }
    } else {
        Warn "nvidia-smi not found; the Nvidia driver may be missing or very old. Install the latest driver from nvidia.com/drivers if anything fails."
        $Gpu = "nvidia_cu126"
    }
    if ($vramGB -gt 0 -and $vramGB -lt 8) { Warn "$vramGB GB of video memory is below the 8 GB minimum. It may not run." }
} elseif ($Gpu -eq "amd") {
    $amdName = ($cards | Where-Object { $_ -match "AMD|Radeon" } | Select-Object -First 1)
    # ComfyUI's AMD build uses ROCm, which supports Radeon RX 7000 / 9000 series and recent Ryzen AI chips.
    if ($amdName -and $amdName -notmatch "RX\s*(7\d{3}|9\d{3})|Radeon\s*(8\d{2}0?M|8060S|8050S|890M|880M)|AI\s*(Max|300)|W7\d{3}|R9\d{3}") {
        Warn "'$amdName' may be too old for ComfyUI's AMD build (it supports Radeon RX 7000 and 9000 series)."
        Warn "The install will continue, but the picture splitting may fail to start on this card."
    }
    Info "Using ComfyUI's AMD (ROCm) build. AMD support is newer than Nvidia's; update to the latest AMD Adrenalin driver first."
} elseif ($Gpu -eq "intel") {
    Warn "Intel Arc support is experimental and untested with See-through."
}

$archive = switch ($Gpu) {
    "nvidia"       { "ComfyUI_windows_portable_nvidia.7z" }
    "nvidia_cu126" { "ComfyUI_windows_portable_nvidia_cu126.7z" }
    "amd"          { "ComfyUI_windows_portable_amd.7z" }
    "intel"        { "ComfyUI_windows_portable_intel.7z" }
}
$launcher = switch ($Gpu) {
    "amd"   { "run_amd_gpu.bat" }
    "intel" { "run_intel_gpu.bat" }
    default { "run_nvidia_gpu.bat" }
}
Info "ComfyUI build: $archive"

# ---------------------------------------------------------------- Visual C++ runtime
$vc = Get-ItemProperty -ErrorAction SilentlyContinue "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
if (-not $vc -or $vc.Installed -ne 1) {
    Say "Installing the Microsoft Visual C++ runtime (Windows will ask for permission)"
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $vcExe = Join-Path $InstallDir "vc_redist.x64.exe"
    Download "https://aka.ms/vs/17/release/vc_redist.x64.exe" $vcExe
    try {
        $p = Start-Process -FilePath $vcExe -ArgumentList "/install", "/passive", "/norestart" -Verb RunAs -Wait -PassThru
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010 -and $p.ExitCode -ne 1638) { Warn "Visual C++ runtime installer returned $($p.ExitCode). Continuing." }
    } catch {
        Warn "The Visual C++ runtime was not installed (permission declined?). ComfyUI may fail to start with a 'c10.dll' error; run the installer again and click Yes."
    }
    Remove-Item -Force -ErrorAction SilentlyContinue $vcExe
}

# ---------------------------------------------------------------- ComfyUI portable
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$portable = Join-Path $InstallDir "ComfyUI_windows_portable"
$py = Join-Path $portable "python_embeded\python.exe"
$comfy = Join-Path $portable "ComfyUI"

if (Test-Path $py) {
    Say "ComfyUI is already installed, skipping"
} else {
    Say "Downloading ComfyUI $ComfyVersion (about 2 GB)"
    $dl = Join-Path $InstallDir "_downloads"
    New-Item -ItemType Directory -Force -Path $dl | Out-Null
    $sevenZip = Join-Path $dl "7zr.exe"
    if (-not (Test-Path $sevenZip)) { Download "https://www.7-zip.org/a/7zr.exe" $sevenZip }
    $archivePath = Join-Path $dl $archive
    if (-not (Test-Path $archivePath)) {
        Download "https://github.com/Comfy-Org/ComfyUI/releases/download/$ComfyVersion/$archive" $archivePath
    }
    Say "Unpacking ComfyUI (a few minutes)"
    $unpack = Join-Path $InstallDir "_unpack"
    if (Test-Path $unpack) { Remove-Item -Recurse -Force $unpack }
    Native { & $sevenZip x $archivePath "-o$unpack" -y -bso0 -bsp1 }
    if ($LASTEXITCODE -ne 0) { Fail "Unpacking failed. The download may be damaged; delete $dl and run again." }
    $found = Get-ChildItem -Path $unpack -Recurse -Depth 2 -Filter "python.exe" |
        Where-Object { $_.Directory.Name -eq "python_embeded" } | Select-Object -First 1
    if (-not $found) { Fail "Unexpected ComfyUI package layout (no python_embeded folder)." }
    Move-Item -Force $found.Directory.Parent.FullName $portable
    Remove-Item -Recurse -Force $unpack
    Remove-Item -Recurse -Force $dl
}
if (-not (Test-Path (Join-Path $portable $launcher))) {
    $any = Get-ChildItem -Path $portable -Filter "run_*gpu*.bat" | Select-Object -First 1
    if ($any) { $launcher = $any.Name }
}

# ---------------------------------------------------------------- SeeThrough nodes
Say "Installing the SeeThrough nodes"
$nodeDir = Join-Path $comfy "custom_nodes\$NodeName"
$staging = Join-Path $InstallDir "_node"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
if ($NodeSource) {
    Copy-Item -Recurse -Force $NodeSource $staging
    if (Test-Path (Join-Path $staging ".git")) { Remove-Item -Recurse -Force (Join-Path $staging ".git") }
} else {
    $zip = Join-Path $InstallDir "_node.zip"
    Download "https://github.com/$Repo/archive/refs/heads/$Branch.zip" $zip
    $ex = Join-Path $InstallDir "_node_unzip"
    if (Test-Path $ex) { Remove-Item -Recurse -Force $ex }
    Expand-Archive -Path $zip -DestinationPath $ex -Force
    $inner = Get-ChildItem $ex -Directory | Select-Object -First 1
    Move-Item $inner.FullName $staging
    Remove-Item -Recurse -Force $ex
    Remove-Item -Force $zip
}
if (Test-Path $nodeDir) { Remove-Item -Recurse -Force $nodeDir }
Move-Item $staging $nodeDir
Info "Nodes in $nodeDir"

Say "Installing Python packages for SeeThrough"
Native { & $py -s -m pip install --no-warn-script-location --disable-pip-version-check -r (Join-Path $nodeDir "requirements.txt") }
if ($LASTEXITCODE -ne 0) { Fail "pip could not install the requirements (see the messages above)." }
if ($Gpu -like "nvidia*") {
    Native { & $py -s -m pip install --no-warn-script-location --disable-pip-version-check "bitsandbytes>=0.49.2" }
    if ($LASTEXITCODE -ne 0) { Warn "bitsandbytes failed to install; the 4-bit mode for small cards will not be available." }
}

# quick self-test: can ComfyUI's Python import everything the nodes need?
Native { & $py -s -c "import diffusers, peft, accelerate, cv2, sklearn, huggingface_hub, torch; print('    torch', torch.__version__, '| GPU available:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')" }
if ($LASTEXITCODE -ne 0) { Fail "The Python packages did not import correctly." }

# ---------------------------------------------------------------- models
if ($SkipModels) {
    Say "Skipping the model download (the first run will download them)"
} else {
    $variant = "bf16"
    if ($Gpu -like "nvidia*" -and $vramGB -gt 0 -and $vramGB -lt 10) { $variant = "nf4" }
    $size = if ($variant -eq "nf4") { "about 6 GB" } else { "about 13 GB" }
    Say "Downloading the See-through models ($size, only once; resumes if interrupted)"
    Native { & $py -s (Join-Path $nodeDir "seethrough_models.py") --models-dir (Join-Path $comfy "models\SeeThrough") --variant $variant }
    if ($LASTEXITCODE -ne 0) { Fail "Model download failed. Run the installer again to resume." }
}

# ---------------------------------------------------------------- workflow, launcher, shortcut
$wfDir = Join-Path $comfy "user\default\workflows"
New-Item -ItemType Directory -Force -Path $wfDir | Out-Null
Copy-Item -Force (Join-Path $nodeDir "example_workflows\SeeThrough-Easy.json") (Join-Path $wfDir "SeeThrough-Easy.json")
$inputDir = Join-Path $comfy "input"
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
Copy-Item -Force (Join-Path $nodeDir "assets\seethrough_example.png") (Join-Path $inputDir "seethrough_example.png")

$startBat = Join-Path $InstallDir "Start SeeThrough.bat"
@"
@echo off
title SeeThrough (ComfyUI) - keep this window open while you use it
cd /d "$portable"
call "$launcher"
"@ | Set-Content -Encoding ASCII $startBat

$updateBat = Join-Path $InstallDir "Update SeeThrough.bat"
@"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/$Repo/$Branch/windows/install.ps1'))) -InstallDir '$InstallDir'"
pause
"@ | Set-Content -Encoding ASCII $updateBat

$outDir = Join-Path $comfy "output"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

if (-not $NoShortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut((Join-Path $desktop "SeeThrough.lnk"))
    $lnk.TargetPath = $startBat
    $lnk.WorkingDirectory = $portable
    $lnk.Description = "Start SeeThrough (ComfyUI)"
    $lnk.Save()
    $lnk2 = $ws.CreateShortcut((Join-Path $desktop "SeeThrough results.lnk"))
    $lnk2.TargetPath = $outDir
    $lnk2.Save()
}

Write-Host ""
Write-Host "  Done!" -ForegroundColor Green
Write-Host ""
Write-Host "  To use it:"
Write-Host "   1. Double-click 'SeeThrough' on the desktop. A black window opens, then your browser."
Write-Host "      Keep the black window open while you work."
Write-Host "   2. In the browser, press W (or click 'Workflows' on the left) and open 'SeeThrough-Easy'."
Write-Host "   3. Load your picture in the 'Load Image' box and press Run."
Write-Host "   4. Results: the 'SeeThrough results' folder on the desktop, or 'Download PSD' on the last box."
Write-Host ""
Write-Host "  To update later: run '$updateBat'."
Write-Host ""
