#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$DistroName = 'Ubuntu-24.04',
    [string]$ProjectPath = $PSScriptRoot,
    [switch]$CheckOnly,
    [switch]$AutoReboot
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$MinimumBuild = 19041
$MinimumMemoryGB = 4
$RecommendedMemoryGB = 8
$MinimumDiskGB = 20
$RecommendedDiskGB = 30
$ResumeName = 'DataAnonymizationWslInstaller'
$WslBootstrap = @'
#!/usr/bin/env bash
set -Eeuo pipefail

PHASE="${1:-all}"
PROJECT_DIR="${2:-}"
APT_MIRROR="https://mirrors.tuna.tsinghua.edu.cn"
PYPI_MIRROR="https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
NPM_MIRROR="https://registry.npmmirror.com"
DOCKER_CE_MIRROR="https://mirrors.tuna.tsinghua.edu.cn/docker-ce"
DOCKER_HUB_PREFIX="m.daocloud.io/docker.io/library/"
DOCKER_REGISTRY_MIRROR="https://docker.m.daocloud.io"

log() {
    printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

retry() {
    local attempt=1
    local max_attempts=3
    until "$@"; do
        if (( attempt >= max_attempts )); then
            return 1
        fi
        log "命令执行失败，正在进行第 $((attempt + 1)) 次尝试……"
        attempt=$((attempt + 1))
        sleep 3
    done
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "必须以 root 身份运行 WSL 内部安装流程。" >&2
        exit 1
    fi
}

configure_ubuntu_mirror() {
    log "配置 Ubuntu 清华大学镜像源"
    if [[ -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
        cp -n /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources.before-data-anonymization || true
        sed -i \
            -e "s|https\?://archive.ubuntu.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
            -e "s|https\?://security.ubuntu.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
            -e "s|https\?://ports.ubuntu.com/ubuntu-ports|${APT_MIRROR}/ubuntu-ports|g" \
            /etc/apt/sources.list.d/ubuntu.sources
    elif [[ -f /etc/apt/sources.list ]]; then
        cp -n /etc/apt/sources.list /etc/apt/sources.list.before-data-anonymization || true
        sed -i \
            -e "s|https\?://archive.ubuntu.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
            -e "s|https\?://security.ubuntu.com/ubuntu|${APT_MIRROR}/ubuntu|g" \
            -e "s|https\?://ports.ubuntu.com/ubuntu-ports|${APT_MIRROR}/ubuntu-ports|g" \
            /etc/apt/sources.list
    else
        echo "未找到 Ubuntu APT 源配置。" >&2
        exit 1
    fi

    retry apt-get update
    DEBIAN_FRONTEND=noninteractive retry apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg openssl jq
}

configure_pip_mirror() {
    log "配置 WSL 全局 PyPI 国内镜像"
    cat >/etc/pip.conf <<EOF
[global]
index-url = ${PYPI_MIRROR}
timeout = 120
disable-pip-version-check = true
EOF
}

install_docker() {
    local docker_version=""
    local compose_version=""
    if command -v docker >/dev/null 2>&1; then
        docker_version="$(docker --version 2>/dev/null | sed -nE 's/.*version ([0-9]+(\.[0-9]+)+).*/\1/p')"
        compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
    fi
    if [[ -n "$docker_version" && -n "$compose_version" ]] \
        && dpkg --compare-versions "$docker_version" ge 24.0 \
        && dpkg --compare-versions "$compose_version" ge 2.20; then
        log "Docker Engine ${docker_version} 与 Compose ${compose_version} 已满足要求"
        return
    elif [[ -n "$docker_version" || -n "$compose_version" ]]; then
        log "现有 Docker/Compose 版本过旧或不完整，将升级到当前稳定版"
    fi

    log "通过清华大学 Docker CE 镜像仓库安装 Docker Engine"
    DEBIAN_FRONTEND=noninteractive apt-get remove -y \
        docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc \
        >/dev/null 2>&1 || true
    install -m 0755 -d /etc/apt/keyrings
    retry curl -fsSL "${DOCKER_CE_MIRROR}/linux/ubuntu/gpg" -o /tmp/docker-ce.asc
    gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg /tmp/docker-ce.asc
    chmod a+r /etc/apt/keyrings/docker.gpg
    rm -f /tmp/docker-ce.asc

    # shellcheck disable=SC1091
    . /etc/os-release
    local codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    if [[ -z "$codename" ]]; then
        echo "无法确定 Ubuntu 版本代号。" >&2
        exit 1
    fi
    cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: ${DOCKER_CE_MIRROR}/linux/ubuntu
Suites: ${codename}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.gpg
EOF
    retry apt-get update
    DEBIAN_FRONTEND=noninteractive retry apt-get install -y \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

configure_docker_mirror() {
    log "配置 Docker Hub 中国大陆镜像加速"
    install -d -m 0755 /etc/docker
    if [[ -s /etc/docker/daemon.json ]]; then
        if ! jq empty /etc/docker/daemon.json >/dev/null 2>&1; then
            echo "现有 /etc/docker/daemon.json 不是合法 JSON，脚本不会覆盖它。" >&2
            exit 1
        fi
        cp -n /etc/docker/daemon.json /etc/docker/daemon.json.before-data-anonymization || true
        local temp_file
        temp_file="$(mktemp)"
        jq --arg mirror "$DOCKER_REGISTRY_MIRROR" '. + {"registry-mirrors": [$mirror]}' \
            /etc/docker/daemon.json >"$temp_file"
        install -m 0644 "$temp_file" /etc/docker/daemon.json
        rm -f "$temp_file"
    else
        cat >/etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["${DOCKER_REGISTRY_MIRROR}"],
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
EOF
    fi
}

enable_systemd() {
    log "启用 WSL systemd，使 Docker 随 WSL 自动启动"
    touch /etc/wsl.conf
    if grep -Eq '^[[:space:]]*systemd[[:space:]]*=' /etc/wsl.conf; then
        sed -i -E 's/^[[:space:]]*systemd[[:space:]]*=.*/systemd=true/' /etc/wsl.conf
    elif grep -Eq '^\[boot\]' /etc/wsl.conf; then
        sed -i '/^\[boot\]/a systemd=true' /etc/wsl.conf
    else
        printf '\n[boot]\nsystemd=true\n' >>/etc/wsl.conf
    fi
    systemctl enable docker.service containerd.service >/dev/null 2>&1 || true
}

start_docker() {
    log "启动并检查 Docker Engine"
    if command -v systemctl >/dev/null 2>&1 && [[ "$(ps -p 1 -o comm=)" == "systemd" ]]; then
        systemctl enable --now docker.service containerd.service
    else
        service docker start
    fi
    local attempt
    for attempt in {1..30}; do
        if docker info >/dev/null 2>&1; then
            docker version
            docker compose version
            return
        fi
        sleep 2
    done
    echo "Docker Engine 未能在 60 秒内启动。" >&2
    exit 1
}

write_secure_environment() {
    local env_file="${PROJECT_DIR}/.env"
    if [[ -f "$env_file" ]]; then
        log "检测到现有 .env，保留原配置"
        if grep -Eq '=(please-change-|local-dev-)' "$env_file"; then
            echo "现有 .env 仍含示例弱密钥。请删除它让脚本生成随机密钥，或手工替换示例值。" >&2
            exit 1
        fi
        return
    fi

    log "生成随机数据库密码与应用加密密钥"
    umask 077
    local allowed_hosts="${APP_ALLOWED_HOSTS:-localhost,127.0.0.1}"
    cat >"$env_file" <<EOF
DJANGO_SECRET_KEY=$(openssl rand -hex 48)
MAPPING_ENCRYPTION_KEY=$(openssl rand -hex 48)
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 32)
MYSQL_DATABASE=data_anonymization
MYSQL_USER=anonymizer
MYSQL_PASSWORD=$(openssl rand -hex 32)
DJANGO_DEBUG=0
ALLOWED_HOSTS=${allowed_hosts}
MAX_UPLOAD_SIZE_MB=50
DATA_RETENTION_DAYS=30
MYSQL_IMAGE=${DOCKER_HUB_PREFIX}mysql:8.4
PYTHON_IMAGE=${DOCKER_HUB_PREFIX}python:3.13-slim
NODE_IMAGE=${DOCKER_HUB_PREFIX}node:22-alpine
NGINX_IMAGE=${DOCKER_HUB_PREFIX}nginx:1.27-alpine
PIP_INDEX_URL=${PYPI_MIRROR}
NPM_REGISTRY=${NPM_MIRROR}
DEBIAN_MIRROR=${APT_MIRROR}/debian
EOF
    chmod 600 "$env_file"
}

prepare_system() {
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" ]]; then
        echo "当前自动流程仅支持 Ubuntu WSL，检测到：${PRETTY_NAME:-unknown}" >&2
        exit 1
    fi
    configure_ubuntu_mirror
    configure_pip_mirror
    install_docker
    configure_docker_mirror
    enable_systemd
}

deploy_application() {
    if [[ -z "$PROJECT_DIR" || ! -f "${PROJECT_DIR}/docker-compose.yml" ]]; then
        echo "项目目录无效或缺少 docker-compose.yml：${PROJECT_DIR}" >&2
        exit 1
    fi
    start_docker
    write_secure_environment
    log "使用国内镜像构建并启动数据脱敏应用"
    cd "$PROJECT_DIR"
    retry docker compose pull db nginx
    docker compose up -d --build --remove-orphans

    log "等待应用健康检查"
    local attempt
    for attempt in {1..60}; do
        if curl -fsS http://127.0.0.1:5291/api/health/ >/dev/null 2>&1; then
            docker compose ps
            printf '\n部署成功：http://localhost:5291\n'
            return
        fi
        sleep 3
    done
    docker compose ps
    docker compose logs --tail=100
    echo "应用未能在 180 秒内通过健康检查。" >&2
    exit 1
}

require_root
case "$PHASE" in
    prepare) prepare_system ;;
    deploy) deploy_application ;;
    *) echo "未知安装阶段：$PHASE" >&2; exit 2 ;;
esac
'@

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-WindowsArchitecture($ComputerSystem, $OperatingSystem) {
    $candidates = @(
        $env:PROCESSOR_ARCHITEW6432,
        $env:PROCESSOR_ARCHITECTURE,
        $ComputerSystem.SystemType,
        $OperatingSystem.OSArchitecture
    )
    foreach ($candidate in $candidates) {
        $value = [string]$candidate
        if ([string]::IsNullOrWhiteSpace($value)) { continue }
        if ($value -match '(?i)(ARM64|ARM-based)') { return 'Arm64' }
        if ($value -match '(?i)(AMD64|x64|x86-based PC)') { return 'X64' }
    }
    return 'Unknown'
}

function Get-ProjectDiskInfo([string]$ResolvedPath) {
    $root = [IO.Path]::GetPathRoot($ResolvedPath)
    if ([string]::IsNullOrWhiteSpace($root) -or $root.Length -lt 2) {
        return $null
    }
    $deviceId = $root.Substring(0, 2)
    return Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$deviceId'" -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Write-WslBootstrap([string]$TargetPath) {
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    $linuxText = $WslBootstrap -replace "`r`n", "`n"
    [IO.File]::WriteAllText($TargetPath, $linuxText, $utf8WithoutBom)
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Start-ElevatedCopy {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DistroName `"$DistroName`" -ProjectPath `"$ProjectPath`""
    if ($CheckOnly) { $arguments += ' -CheckOnly' }
    if ($AutoReboot) { $arguments += ' -AutoReboot' }
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments
}

function Set-ResumeAfterRestart {
    $command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DistroName `"$DistroName`" -ProjectPath `"$ProjectPath`""
    if ($AutoReboot) { $command += ' -AutoReboot' }
    New-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce' `
        -Name $ResumeName -Value $command -PropertyType String -Force | Out-Null
}

function Clear-ResumeAfterRestart {
    Remove-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce' `
        -Name $ResumeName -ErrorAction SilentlyContinue
}

function Stop-ForRestart {
    Set-ResumeAfterRestart
    Write-Warning 'WSL2 系统组件已启用，需要重启 Windows。登录后安装脚本会自动继续。'
    if ($AutoReboot) {
        Write-Warning '15 秒后自动重启。若要取消，请立即运行：shutdown /a'
        shutdown.exe /r /t 15 /c '继续安装数据脱敏应用所需的 WSL2'
    } else {
        Write-Host '请保存工作并手动重启 Windows；下次登录时脚本会自动续跑。' -ForegroundColor Yellow
    }
    exit 3010
}

if (-not (Test-Administrator)) {
    Write-Host '正在请求管理员权限……' -ForegroundColor Yellow
    Start-ElevatedCopy
    exit 0
}

$resolvedProject = [IO.Path]::GetFullPath($ProjectPath)
$runtimeDirectory = Join-Path $resolvedProject '.runtime'
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$logPath = Join-Path $runtimeDirectory ('install-wsl-docker-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
Start-Transcript -Path $logPath -Append | Out-Null

try {
    Write-Step '检测 Windows、硬件与部署资源'
    $os = Get-CimInstance Win32_OperatingSystem
    $computer = Get-CimInstance Win32_ComputerSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    if (-not $os) { throw '无法读取 Win32_OperatingSystem 系统信息。请确认 WMI/CIM 服务正在运行。' }
    if (-not $computer) { throw '无法读取 Win32_ComputerSystem 硬件信息。请确认 WMI/CIM 服务正在运行。' }
    if (-not $cpu) { throw '无法读取 Win32_Processor 处理器信息。请确认 WMI/CIM 服务正在运行。' }
    $build = [int]$os.BuildNumber
    $memoryGB = [math]::Round($computer.TotalPhysicalMemory / 1GB, 1)
    $architecture = Get-WindowsArchitecture $computer $os
    $disk = Get-ProjectDiskInfo $resolvedProject
    $diskFreeGB = if ($disk -and $null -ne $disk.FreeSpace) { [math]::Round($disk.FreeSpace / 1GB, 1) } else { 0 }
    $virtualization = [bool]$computer.HypervisorPresent -or [bool]$cpu.VirtualizationFirmwareEnabled
    $portOwner = Get-NetTCPConnection -State Listen -LocalPort 5291 -ErrorAction SilentlyContinue | Select-Object -First 1

    $wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
    $vmFeature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform

    $mirrorEndpoints = [ordered]@{
        '清华 Docker CE' = 'https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu/gpg'
        '清华 PyPI' = 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/django/'
        'npmmirror' = 'https://registry.npmmirror.com/vue'
        'DaoCloud 容器镜像' = 'https://m.daocloud.io/v2/'
    }
    $mirrorChecks = foreach ($endpoint in $mirrorEndpoints.GetEnumerator()) {
        $reachable = $false
        try {
            $null = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $endpoint.Value -TimeoutSec 15
            $reachable = $true
        } catch {
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
                # Docker Registry v2 使用 401 响应发起标准匿名令牌认证挑战。
                $reachable = $true
            }
        }
        [pscustomobject]@{ Name = $endpoint.Key; Reachable = $reachable; Url = $endpoint.Value }
    }

    $results = @(
        [pscustomobject]@{ Item = 'Windows'; Result = $os.Caption; Required = 'Windows 10 2004 / Build 19041 或 Windows 11' }
        [pscustomobject]@{ Item = '系统版本'; Result = "Build $build"; Required = "Build >= $MinimumBuild" }
        [pscustomobject]@{ Item = '体系结构'; Result = $architecture; Required = 'X64 或 Arm64' }
        [pscustomobject]@{ Item = 'CPU 虚拟化'; Result = if ($virtualization) { '已启用' } else { '未检测到' }; Required = 'BIOS/UEFI 中启用' }
        [pscustomobject]@{ Item = '物理内存'; Result = "$memoryGB GB"; Required = ">= $MinimumMemoryGB GB，建议 >= $RecommendedMemoryGB GB" }
        [pscustomobject]@{ Item = '项目盘可用空间'; Result = "$diskFreeGB GB"; Required = ">= $MinimumDiskGB GB，建议 >= $RecommendedDiskGB GB" }
        [pscustomobject]@{ Item = 'WSL 组件'; Result = $wslFeature.State; Required = 'Enabled（脚本可自动启用）' }
        [pscustomobject]@{ Item = '虚拟机平台'; Result = $vmFeature.State; Required = 'Enabled（脚本可自动启用）' }
        [pscustomobject]@{ Item = '应用端口 5291'; Result = if ($portOwner) { "已占用，PID $($portOwner.OwningProcess)" } else { '可用' }; Required = '部署时需可用' }
        [pscustomobject]@{ Item = '国内镜像网络'; Result = if ($mirrorChecks.Reachable -notcontains $false) { '全部可访问' } else { '存在不可访问端点' }; Required = '清华、npmmirror、DaoCloud 可访问' }
    )
    $results | Format-Table -AutoSize

    $blocking = New-Object System.Collections.Generic.List[string]
    if ($build -lt $MinimumBuild) { $blocking.Add("Windows Build $build 低于 $MinimumBuild，请先运行 Windows Update。") }
    if ($architecture -notin @('X64', 'Arm64')) { $blocking.Add("不支持的体系结构：$architecture。") }
    if (-not $virtualization) { $blocking.Add('未检测到硬件虚拟化，请在 BIOS/UEFI 中启用 Intel VT-x 或 AMD-V。') }
    if ($memoryGB -lt $MinimumMemoryGB) { $blocking.Add("内存不足 $MinimumMemoryGB GB。") }
    if ($diskFreeGB -lt $MinimumDiskGB) { $blocking.Add("项目所在磁盘可用空间不足 $MinimumDiskGB GB。") }
    if (-not (Test-Path (Join-Path $resolvedProject 'docker-compose.yml'))) { $blocking.Add('项目目录缺少 docker-compose.yml。') }
    foreach ($failedMirror in @($mirrorChecks | Where-Object { -not $_.Reachable })) {
        $blocking.Add("国内镜像不可访问：$($failedMirror.Name)（$($failedMirror.Url)）。")
    }

    if ($memoryGB -lt $RecommendedMemoryGB -and $memoryGB -ge $MinimumMemoryGB) {
        Write-Warning "内存低于建议值 $RecommendedMemoryGB GB，首次构建可能较慢。"
    }
    if ($diskFreeGB -lt $RecommendedDiskGB -and $diskFreeGB -ge $MinimumDiskGB) {
        Write-Warning "磁盘空间低于建议值 $RecommendedDiskGB GB，请定期清理不用的 Docker 镜像。"
    }
    if ($portOwner) {
        Write-Warning "端口 5291 当前由 PID $($portOwner.OwningProcess) 监听；若不是本项目，部署会失败。"
    }
    if ($blocking.Count -gt 0) {
        throw ("系统不符合安装要求：`n- " + ($blocking -join "`n- "))
    }
    if ($CheckOnly) {
        Write-Host "`n系统满足最低安装要求；未修改任何 WSL 或 Docker 配置。" -ForegroundColor Green
        exit 0
    }

    Write-Step '启用 WSL2 所需的 Windows 功能'
    $restartNeeded = $false
    if ($wslFeature.State -ne 'Enabled') {
        $featureResult = Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart
        $restartNeeded = $restartNeeded -or $featureResult.RestartNeeded
    }
    if ($vmFeature.State -ne 'Enabled') {
        $featureResult = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
        $restartNeeded = $restartNeeded -or $featureResult.RestartNeeded
    }
    if ($wslFeature.State -ne 'Enabled' -or $vmFeature.State -ne 'Enabled' -or $restartNeeded) {
        Stop-ForRestart
    }

    Write-Step "安装并初始化 $DistroName（WSL2）"
    & wsl.exe --update
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'WSL 运行时在线更新未完成，将继续使用当前已安装版本。'
    }
    & wsl.exe --set-default-version 2
    if ($LASTEXITCODE -ne 0) { throw '无法把 WSL 默认版本设为 2。请先完成 Windows Update。' }

    $installedDistros = @(& wsl.exe --list --quiet 2>$null | ForEach-Object {
        ([string]($_ -replace "`0", '')).Trim()
    } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($DistroName -notin $installedDistros) {
        & wsl.exe --install --distribution $DistroName --no-launch
        if ($LASTEXITCODE -ne 0) {
            Write-Warning '常规 WSL 下载失败，改用 Microsoft Web Download 通道重试。'
            & wsl.exe --install --web-download --distribution $DistroName --no-launch
            if ($LASTEXITCODE -ne 0) { throw "$DistroName 安装失败。" }
        }
    }

    & wsl.exe --set-version $DistroName 2
    if ($LASTEXITCODE -ne 0) { throw "无法把 $DistroName 转换为 WSL2。" }
    & wsl.exe --distribution $DistroName --user root -- bash -lc 'true'
    if ($LASTEXITCODE -ne 0) { throw "$DistroName 初始化失败。" }

    $linuxProjectOutput = & wsl.exe --distribution $DistroName --user root -- wslpath -a $resolvedProject | Select-Object -Last 1
    $linuxProject = ([string]$linuxProjectOutput).Trim()
    if ([string]::IsNullOrWhiteSpace($linuxProject)) { throw '无法把 Windows 项目目录转换为 WSL 路径。' }
    $bootstrapPath = Join-Path $runtimeDirectory 'wsl-bootstrap.sh'
    Write-WslBootstrap $bootstrapPath
    $linuxInstallerOutput = & wsl.exe --distribution $DistroName --user root -- wslpath -a $bootstrapPath | Select-Object -Last 1
    $linuxInstaller = ([string]$linuxInstallerOutput).Trim()
    if ([string]::IsNullOrWhiteSpace($linuxInstaller)) { throw '无法创建内嵌的 WSL 安装流程。' }

    Write-Step '在 WSL 中配置国内镜像并安装 Docker Engine'
    & wsl.exe --distribution $DistroName --user root -- bash $linuxInstaller prepare $linuxProject
    if ($LASTEXITCODE -ne 0) { throw 'WSL 内的 Docker 安装或镜像配置失败。' }

    Write-Step '重启 WSL，使 systemd 与 Docker 服务生效'
    & wsl.exe --shutdown
    Start-Sleep -Seconds 3

    $hostAddresses = @('localhost', '127.0.0.1')
    $hostAddresses += @(Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp, Manual -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } |
        Select-Object -ExpandProperty IPAddress)
    $allowedHosts = ($hostAddresses | Select-Object -Unique) -join ','

    Write-Step '生成安全配置、构建容器并启动应用'
    & wsl.exe --distribution $DistroName --user root -- env "APP_ALLOWED_HOSTS=$allowedHosts" bash $linuxInstaller deploy $linuxProject
    if ($LASTEXITCODE -ne 0) { throw 'Docker 容器部署失败。' }

    $envPath = Join-Path $resolvedProject '.env'
    if (Test-Path -LiteralPath $envPath) {
        Write-Step '收紧 .env 的 Windows NTFS 访问权限'
        $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        & icacls.exe $envPath /inheritance:r /grant:r "*${currentSid}:(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning '无法设置 .env 的 NTFS ACL。请确认项目位于 NTFS 磁盘，并手工限制该文件权限。'
        }
    }

    Write-Step '从 Windows 检查应用端口与健康状态'
    $healthy = $false
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:5291/api/health/' -TimeoutSec 5
            if ($response.StatusCode -eq 200) { $healthy = $true; break }
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    if (-not $healthy) { throw '容器已启动，但 Windows 无法访问 http://localhost:5291/api/health/。' }

    Clear-ResumeAfterRestart
    Remove-Item -LiteralPath $bootstrapPath -Force -ErrorAction SilentlyContinue
    Write-Host "`n安装和部署全部完成：http://localhost:5291" -ForegroundColor Green
    Write-Host "安装日志：$logPath"
}
catch {
    Write-Host "`n安装失败：$($_.Exception.Message)" -ForegroundColor Red
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Host "错误位置：$($_.InvocationInfo.PositionMessage)" -ForegroundColor Red
    }
    if ($_.ScriptStackTrace) {
        Write-Host "调用栈：$($_.ScriptStackTrace)" -ForegroundColor DarkRed
    }
    Write-Host "日志位置：$logPath" -ForegroundColor Yellow
    exit 1
}
finally {
    if (Get-Variable -Name bootstrapPath -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $bootstrapPath -Force -ErrorAction SilentlyContinue
    }
    try { Stop-Transcript | Out-Null } catch { }
}
