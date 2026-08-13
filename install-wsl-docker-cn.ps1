#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$DistroName = 'Ubuntu-24.04',
    [string]$ProjectPath = $PSScriptRoot,
    [ValidateSet('Auto', 'Store', 'Web')]
    [string]$WslDownloadChannel = 'Auto',
    [ValidateRange(5, 60)]
    [int]$ProgressIntervalSeconds = 10,
    [switch]$CheckOnly,
    [switch]$AutoReboot,
    [switch]$ResumeAfterRestart
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$MinimumBuild = 19041
$MinimumMemoryGB = 4
$RecommendedMemoryGB = 8
$MinimumDiskGB = 20
$RecommendedDiskGB = 30
$MinimumWslVersion = [version]'0.67.6'
$MinimumDockerVersion = '24.0'
$MaximumDockerVersion = '30.0'
$MinimumComposeVersion = '2.20'
$MaximumComposeVersion = '6.0'
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
DOCKER_MIN_VERSION="24.0"
DOCKER_MAX_VERSION="30.0"
COMPOSE_MIN_VERSION="2.20"
COMPOSE_MAX_VERSION="6.0"

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
    local docker_supported=false
    local compose_supported=false
    if command -v docker >/dev/null 2>&1; then
        docker_version="$(docker --version 2>/dev/null | sed -nE 's/.*version ([0-9]+(\.[0-9]+)+).*/\1/p')"
        compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
    fi
    if [[ -n "$docker_version" ]] && dpkg --compare-versions "$docker_version" ge "$DOCKER_MAX_VERSION"; then
        echo "Docker Engine ${docker_version} 超出支持范围 [${DOCKER_MIN_VERSION}, ${DOCKER_MAX_VERSION})。脚本不会自动降级，请先按部署文档处理。" >&2
        exit 1
    fi
    if [[ -n "$compose_version" ]] && dpkg --compare-versions "$compose_version" ge "$COMPOSE_MAX_VERSION"; then
        echo "Docker Compose ${compose_version} 超出支持范围 [${COMPOSE_MIN_VERSION}, ${COMPOSE_MAX_VERSION})。脚本不会自动降级，请先按部署文档处理。" >&2
        exit 1
    fi
    if [[ -n "$docker_version" ]] \
        && dpkg --compare-versions "$docker_version" ge "$DOCKER_MIN_VERSION" \
        && dpkg --compare-versions "$docker_version" lt "$DOCKER_MAX_VERSION"; then
        docker_supported=true
    fi
    if [[ -n "$compose_version" ]] \
        && dpkg --compare-versions "$compose_version" ge "$COMPOSE_MIN_VERSION" \
        && dpkg --compare-versions "$compose_version" lt "$COMPOSE_MAX_VERSION"; then
        compose_supported=true
    fi
    if [[ "$docker_supported" == true && "$compose_supported" == true ]]; then
        log "Docker Engine ${docker_version} 与 Compose ${compose_version} 位于支持范围，跳过重复安装"
        return
    fi

    if [[ "$docker_supported" == true ]]; then
        log "Docker Engine ${docker_version} 位于支持范围，仅补装/升级 Compose，不重复安装 Engine"
    else
        log "Docker Engine 缺失或低于支持范围，将通过清华大学 Docker CE 镜像仓库安装"
        DEBIAN_FRONTEND=noninteractive apt-get remove -y \
            docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc \
            >/dev/null 2>&1 || true
        # 冲突软件包清理时可能同时移除了由发行版提供的 Compose，统一安装受支持的插件版本。
        compose_supported=false
    fi
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

    local docker_package_version=""
    local compose_package_version=""
    local package_version=""
    local upstream_version=""
    local packages=()
    if [[ "$docker_supported" != true ]]; then
        while IFS= read -r package_version; do
            package_version="$(printf '%s' "$package_version" | xargs)"
            upstream_version="${package_version#*:}"
            upstream_version="${upstream_version%%-*}"
            if dpkg --compare-versions "$upstream_version" ge "$DOCKER_MIN_VERSION" \
                && dpkg --compare-versions "$upstream_version" lt "$DOCKER_MAX_VERSION"; then
                docker_package_version="$package_version"
                break
            fi
        done < <(apt-cache madison docker-ce | awk -F '|' '{print $2}')
        if [[ -z "$docker_package_version" ]]; then
            echo "Docker CE 镜像仓库中没有找到项目支持范围内的 Engine 软件包。" >&2
            exit 1
        fi
        packages+=("docker-ce=${docker_package_version}" "docker-ce-cli=${docker_package_version}" containerd.io docker-buildx-plugin)
    fi
    if [[ "$compose_supported" != true ]]; then
        while IFS= read -r package_version; do
            package_version="$(printf '%s' "$package_version" | xargs)"
            upstream_version="${package_version#*:}"
            upstream_version="${upstream_version%%-*}"
            if dpkg --compare-versions "$upstream_version" ge "$COMPOSE_MIN_VERSION" \
                && dpkg --compare-versions "$upstream_version" lt "$COMPOSE_MAX_VERSION"; then
                compose_package_version="$package_version"
                break
            fi
        done < <(apt-cache madison docker-compose-plugin | awk -F '|' '{print $2}')
        if [[ -z "$compose_package_version" ]]; then
            echo "Docker CE 镜像仓库中没有找到项目支持范围内的 Compose 软件包。" >&2
            exit 1
        fi
        packages+=("docker-compose-plugin=${compose_package_version}")
    fi
    DEBIAN_FRONTEND=noninteractive retry apt-get install -y "${packages[@]}"

    docker_version="$(docker --version 2>/dev/null | sed -nE 's/.*version ([0-9]+(\.[0-9]+)+).*/\1/p')"
    compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
    if [[ -z "$docker_version" || -z "$compose_version" ]] \
        || ! dpkg --compare-versions "$docker_version" ge "$DOCKER_MIN_VERSION" \
        || ! dpkg --compare-versions "$docker_version" lt "$DOCKER_MAX_VERSION" \
        || ! dpkg --compare-versions "$compose_version" ge "$COMPOSE_MIN_VERSION" \
        || ! dpkg --compare-versions "$compose_version" lt "$COMPOSE_MAX_VERSION"; then
        echo "安装后的 Docker/Compose 版本不在支持范围：Engine=${docker_version:-未检测到}，Compose=${compose_version:-未检测到}。" >&2
        exit 1
    fi
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

function ConvertTo-NativeArgument([AllowEmptyString()][string]$Value) {
    if ($null -eq $Value -or $Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Invoke-NativeCommandWithProgress {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$Activity = '正在执行',
        [ValidateRange(5, 60)]
        [int]$HeartbeatSeconds = 10,
        [string]$SlowHint = ''
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (($ArgumentList | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    # 不重定向 WSL 输出：让它直接绘制自带的百分比/下载进度。
    $startInfo.RedirectStandardOutput = $false
    $startInfo.RedirectStandardError = $false

    Write-Host ("[{0}] {1}；下面会显示 WSL 原生进度。" -f (Get-Date -Format 'HH:mm:ss'), $Activity) -ForegroundColor Cyan
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw "无法启动：$FilePath" }
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $slowHintShown = $false
    $cancelled = $false
    try {
        try {
            while (-not $process.WaitForExit($HeartbeatSeconds * 1000)) {
                Write-Host ("[{0}] {1}仍在进行，已用时 {2:mm\:ss}；请勿关闭窗口。" -f `
                    (Get-Date -Format 'HH:mm:ss'), $Activity, $stopwatch.Elapsed) -ForegroundColor DarkCyan
                if (-not $slowHintShown -and -not [string]::IsNullOrWhiteSpace($SlowHint) `
                    -and $stopwatch.Elapsed.TotalSeconds -ge 180) {
                    Write-Warning $SlowHint
                    $slowHintShown = $true
                }
            }
            $process.WaitForExit()
            return [pscustomobject]@{ Output = @(); ExitCode = $process.ExitCode }
        } catch [System.Management.Automation.PipelineStoppedException] {
            $cancelled = $true
            throw
        }
    } finally {
        if ($cancelled -and -not $process.HasExited) {
            try { $process.Kill() } catch { }
        }
        $stopwatch.Stop()
        $process.Dispose()
    }
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [switch]$IgnoreStandardError,
        [switch]$DisplayOutput,
        [string]$Activity = '正在执行',
        [string]$SlowHint = ''
    )

    if ($DisplayOutput) {
        return Invoke-NativeCommandWithProgress -FilePath $FilePath -ArgumentList $ArgumentList `
            -Activity $Activity -HeartbeatSeconds $ProgressIntervalSeconds -SlowHint $SlowHint
    }

    $savedErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 会把原生命令的 stderr 包装成 NativeCommandError；
        # WSL 在返回非零退出码时经常会这样输出可预期的状态提示。
        $ErrorActionPreference = 'Continue'
        if ($IgnoreStandardError) {
            $output = @(& $FilePath @ArgumentList 2>$null)
        } else {
            $output = @(& $FilePath @ArgumentList)
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }

    return [pscustomobject]@{
        Output = $output
        ExitCode = $exitCode
    }
}

function Get-WslRuntimeVersion {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return $null }
    $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--version') -IgnoreStandardError
    if ($result.ExitCode -ne 0) { return $null }
    foreach ($line in $result.Output) {
        $cleanLine = [string]($line -replace "`0", '')
        if ($cleanLine -match '(\d+\.\d+(?:\.\d+){0,2})') {
            try { return [version]$Matches[1] } catch { return $null }
        }
    }
    return $null
}

function Get-InstalledWslDistros {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return @() }
    $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--list', '--quiet') -IgnoreStandardError
    if ($result.ExitCode -ne 0) { return @() }
    return @($result.Output | ForEach-Object {
        ([string]($_ -replace "`0", '')).Trim().TrimStart('*').Trim()
    } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-WslDistroGeneration([string]$Name) {
    $lxssPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (Test-Path $lxssPath) {
        foreach ($key in @(Get-ChildItem -Path $lxssPath -ErrorAction SilentlyContinue)) {
            $properties = Get-ItemProperty -Path $key.PSPath -ErrorAction SilentlyContinue
            if ($properties.DistributionName -eq $Name -and [int]$properties.Version -in @(1, 2)) {
                return [int]$properties.Version
            }
        }
    }

    $escapedName = [regex]::Escape($Name)
    $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--list', '--verbose') -IgnoreStandardError
    foreach ($line in $result.Output) {
        $cleanLine = [string]($line -replace "`0", '')
        if ($cleanLine -match "^\s*\*?\s*$escapedName\s+\S+\s+([12])\s*$") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Get-WslDockerVersions([string]$Name, [int]$Generation) {
    $state = [ordered]@{ Docker = $null; Compose = $null }
    if ($Generation -ne 2) { return [pscustomobject]$state }
    $command = 'docker_version=$(docker --version 2>/dev/null | sed -nE "s/.*version ([0-9]+(\.[0-9]+){1,3}).*/\1/p"); compose_version=$(docker compose version --short 2>/dev/null | sed -nE "s/^v?([0-9]+(\.[0-9]+){1,3}).*/\1/p"); printf "%s|%s\n" "$docker_version" "$compose_version"'
    $result = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $Name, '--user', 'root', '--', 'bash', '-lc', $command) `
        -IgnoreStandardError
    foreach ($line in $result.Output) {
        $cleanLine = ([string]($line -replace "`0", '')).Trim()
        if ($cleanLine -match '^([^|]*)\|([^|]*)$') {
            $state.Docker = if ([string]::IsNullOrWhiteSpace($Matches[1])) { $null } else { $Matches[1] }
            $state.Compose = if ([string]::IsNullOrWhiteSpace($Matches[2])) { $null } else { $Matches[2] }
        }
    }
    return [pscustomobject]$state
}

function Test-VersionInRange([string]$Value, [version]$Minimum, [version]$MaximumExclusive) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    try {
        $version = [version]$Value
        return $version -ge $Minimum -and $version -lt $MaximumExclusive
    } catch {
        return $false
    }
}

function Confirm-Installation {
    $choices = @(
        (New-Object System.Management.Automation.Host.ChoiceDescription '&Yes（是）', '继续安装 WSL2、Docker 并部署应用'),
        (New-Object System.Management.Automation.Host.ChoiceDescription '&No（否）', '退出，不修改 WSL 或 Docker')
    )
    $selection = $Host.UI.PromptForChoice(
        '系统检测通过',
        '系统符合安装要求。是否继续安装和部署？',
        $choices,
        1
    )
    return $selection -eq 0
}

function Start-ElevatedCopy {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DistroName `"$DistroName`" -ProjectPath `"$ProjectPath`" -WslDownloadChannel $WslDownloadChannel -ProgressIntervalSeconds $ProgressIntervalSeconds"
    if ($CheckOnly) { $arguments += ' -CheckOnly' }
    if ($AutoReboot) { $arguments += ' -AutoReboot' }
    if ($ResumeAfterRestart) { $arguments += ' -ResumeAfterRestart' }
    # 保留自动提权后的窗口，让用户能够看到检测结果或错误信息。
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList "-NoExit $arguments"
}

function Set-ResumeAfterRestart {
    $command = "powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DistroName `"$DistroName`" -ProjectPath `"$ProjectPath`" -WslDownloadChannel $WslDownloadChannel -ProgressIntervalSeconds $ProgressIntervalSeconds -ResumeAfterRestart"
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
    return
}

if (-not (Test-Administrator)) {
    Write-Host '正在请求管理员权限……' -ForegroundColor Yellow
    Start-ElevatedCopy
    return
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
        return
    }
    if (-not $ResumeAfterRestart -and -not (Confirm-Installation)) {
        Write-Host "`n已取消安装；未修改任何 WSL 或 Docker 配置。" -ForegroundColor Yellow
        return
    }

    Write-Step '检测主机现有的 WSL、Ubuntu 与 Docker'
    $wslRuntimeVersion = Get-WslRuntimeVersion
    $installedDistros = Get-InstalledWslDistros
    $distroInstalled = $DistroName -in $installedDistros
    $distroGeneration = if ($distroInstalled) { Get-WslDistroGeneration $DistroName } else { $null }
    $wslDocker = if ($distroInstalled) {
        Get-WslDockerVersions $DistroName $distroGeneration
    } else {
        [pscustomobject]@{ Docker = $null; Compose = $null }
    }
    $dockerInRange = Test-VersionInRange $wslDocker.Docker ([version]$MinimumDockerVersion) ([version]$MaximumDockerVersion)
    $composeInRange = Test-VersionInRange $wslDocker.Compose ([version]$MinimumComposeVersion) ([version]$MaximumComposeVersion)
    $installationState = @(
        [pscustomobject]@{
            Item = 'WSL Windows 组件'
            Current = "$($wslFeature.State) / 虚拟机平台 $($vmFeature.State)"
            Action = if ($wslFeature.State -eq 'Enabled' -and $vmFeature.State -eq 'Enabled') { '已安装，跳过' } else { '启用后重启' }
        }
        [pscustomobject]@{
            Item = 'WSL 运行时'
            Current = if ($wslRuntimeVersion) { $wslRuntimeVersion.ToString() } else { '未安装或版本不可识别' }
            Action = if ($wslRuntimeVersion -and $wslRuntimeVersion -ge $MinimumWslVersion) { '满足要求，跳过更新' } else { "更新到 >= $MinimumWslVersion" }
        }
        [pscustomobject]@{
            Item = $DistroName
            Current = if ($distroInstalled) { if ($distroGeneration) { "已安装 / WSL$distroGeneration" } else { '已安装 / 版本待确认' } } else { '未安装' }
            Action = if ($distroGeneration -eq 2) { '已是 WSL2，跳过安装' } elseif ($distroInstalled) { '转换为 WSL2' } else { '安装为 WSL2' }
        }
        [pscustomobject]@{
            Item = 'Docker Engine'
            Current = if ($wslDocker.Docker) { $wslDocker.Docker } else { '未安装' }
            Action = if ($dockerInRange) { '位于支持范围，跳过安装' } else { "要求 >= $MinimumDockerVersion 且 < $MaximumDockerVersion" }
        }
        [pscustomobject]@{
            Item = 'Docker Compose'
            Current = if ($wslDocker.Compose) { $wslDocker.Compose } else { '未安装' }
            Action = if ($composeInRange) { '位于支持范围，跳过安装' } else { "要求 >= $MinimumComposeVersion 且 < $MaximumComposeVersion" }
        }
    )
    $installationState | Format-Table -AutoSize

    if ($wslDocker.Docker -and ([version]$wslDocker.Docker -ge [version]$MaximumDockerVersion)) {
        throw "Docker Engine $($wslDocker.Docker) 超出支持范围 [${MinimumDockerVersion}, ${MaximumDockerVersion})；脚本不会自动降级。"
    }
    if ($wslDocker.Compose -and ([version]$wslDocker.Compose -ge [version]$MaximumComposeVersion)) {
        throw "Docker Compose $($wslDocker.Compose) 超出支持范围 [${MinimumComposeVersion}, ${MaximumComposeVersion})；脚本不会自动降级。"
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
        return
    }

    Write-Step "安装并初始化 $DistroName（WSL2）"
    if (-not $wslRuntimeVersion -or $wslRuntimeVersion -lt $MinimumWslVersion) {
        Write-Host "WSL 未安装或低于 $MinimumWslVersion，开始安装/更新。" -ForegroundColor Yellow
        $updateArguments = if ($WslDownloadChannel -eq 'Web') { @('--update', '--web-download') } else { @('--update') }
        $channelName = if ($WslDownloadChannel -eq 'Web') { 'GitHub 官方 Web 通道' } else { 'Microsoft Store 官方通道' }
        $slowHint = if ($WslDownloadChannel -eq 'Auto') {
            '若百分比一直停在 0%，可按 Ctrl+C 停止后重新运行：.\install-wsl-docker-cn.ps1 -WslDownloadChannel Web'
        } else { '' }
        $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList $updateArguments `
            -DisplayOutput -Activity "通过 $channelName 更新 WSL" -SlowHint $slowHint
        if ($wslResult.ExitCode -ne 0 -and $WslDownloadChannel -eq 'Auto') {
            Write-Warning 'Microsoft Store 通道更新失败，自动切换到 GitHub 官方 Web 下载通道。'
            $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
                -ArgumentList @('--update', '--web-download') -DisplayOutput `
                -Activity '通过 GitHub 官方 Web 通道更新 WSL'
        }
        if ($wslResult.ExitCode -ne 0) {
            throw 'WSL 运行时安装/更新失败。可重试，或使用 -WslDownloadChannel Web 切换到 GitHub 官方通道。'
        }
        $wslRuntimeVersion = Get-WslRuntimeVersion
        if (-not $wslRuntimeVersion -or $wslRuntimeVersion -lt $MinimumWslVersion) {
            throw "WSL 更新后仍未达到 systemd 所需的最低版本 $MinimumWslVersion。"
        }
    } else {
        Write-Host "WSL $wslRuntimeVersion 已满足要求，跳过重复安装/更新。" -ForegroundColor Green
    }
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--set-default-version', '2') `
        -DisplayOutput -Activity '设置默认 WSL 版本为 2'
    if ($wslResult.ExitCode -ne 0) { throw '无法把 WSL 默认版本设为 2。请先完成 Windows Update。' }

    if ($DistroName -notin $installedDistros) {
        $installArguments = @('--install', '--distribution', $DistroName, '--no-launch')
        $installChannelName = 'Microsoft Store 官方通道'
        if ($WslDownloadChannel -eq 'Web') {
            $installArguments = @('--install', '--web-download', '--distribution', $DistroName, '--no-launch')
            $installChannelName = 'GitHub 官方 Web 通道'
        }
        $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
            -ArgumentList $installArguments -DisplayOutput -Activity "通过 $installChannelName 安装 $DistroName" `
            -SlowHint $slowHint
        if ($wslResult.ExitCode -ne 0 -and $WslDownloadChannel -eq 'Auto') {
            Write-Warning '常规 WSL 下载失败，改用 Microsoft Web Download 通道重试。'
            $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
                -ArgumentList @('--install', '--web-download', '--distribution', $DistroName, '--no-launch') `
                -DisplayOutput -Activity "通过 GitHub 官方 Web 通道安装 $DistroName"
        }
        if ($wslResult.ExitCode -ne 0) { throw "$DistroName 安装失败。可改用 -WslDownloadChannel Web 或 Store 后重试。" }
        $installedDistros = Get-InstalledWslDistros
        if ($DistroName -notin $installedDistros) { throw "$DistroName 安装后未出现在 WSL 发行版列表中。" }
    } else {
        Write-Host "$DistroName 已安装，跳过重复安装。" -ForegroundColor Green
    }

    $distroGeneration = Get-WslDistroGeneration $DistroName
    if ($distroGeneration -ne 2) {
        $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--set-version', $DistroName, '2') `
            -DisplayOutput -Activity "将 $DistroName 转换为 WSL2"
        if ($wslResult.ExitCode -ne 0) { throw "无法把 $DistroName 转换为 WSL2。" }
    } else {
        Write-Host "$DistroName 已是 WSL2，跳过版本转换。" -ForegroundColor Green
    }
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'bash', '-lc', 'true') `
        -DisplayOutput -Activity "初始化 $DistroName"
    if ($wslResult.ExitCode -ne 0) { throw "$DistroName 初始化失败。" }

    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'wslpath', '-a', $resolvedProject) `
        -IgnoreStandardError
    $linuxProject = ([string]($wslResult.Output | Select-Object -Last 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($linuxProject)) { throw '无法把 Windows 项目目录转换为 WSL 路径。' }
    $bootstrapPath = Join-Path $runtimeDirectory 'wsl-bootstrap.sh'
    Write-WslBootstrap $bootstrapPath
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'wslpath', '-a', $bootstrapPath) `
        -IgnoreStandardError
    $linuxInstaller = ([string]($wslResult.Output | Select-Object -Last 1)).Trim()
    if ([string]::IsNullOrWhiteSpace($linuxInstaller)) { throw '无法创建内嵌的 WSL 安装流程。' }

    Write-Step '在 WSL 中配置国内镜像并安装 Docker Engine'
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'bash', $linuxInstaller, 'prepare', $linuxProject) `
        -DisplayOutput -Activity '配置大陆镜像并安装 Docker'
    if ($wslResult.ExitCode -ne 0) { throw 'WSL 内的 Docker 安装或镜像配置失败。' }

    Write-Step '重启 WSL，使 systemd 与 Docker 服务生效'
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--shutdown') `
        -DisplayOutput -Activity '关闭 WSL 以应用 systemd 配置'
    if ($wslResult.ExitCode -ne 0) { throw 'WSL 重启失败。' }
    Start-Sleep -Seconds 3

    $hostAddresses = @('localhost', '127.0.0.1')
    $hostAddresses += @(Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp, Manual -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } |
        Select-Object -ExpandProperty IPAddress)
    $allowedHosts = ($hostAddresses | Select-Object -Unique) -join ','

    Write-Step '生成安全配置、构建容器并启动应用'
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'env', "APP_ALLOWED_HOSTS=$allowedHosts", 'bash', $linuxInstaller, 'deploy', $linuxProject) `
        -DisplayOutput -Activity '构建容器并部署应用'
    if ($wslResult.ExitCode -ne 0) { throw 'Docker 容器部署失败。' }

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
    # 抛回调用者而不是退出整个 PowerShell 主机，避免窗口直接关闭。
    throw
}
finally {
    if (Get-Variable -Name bootstrapPath -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $bootstrapPath -Force -ErrorAction SilentlyContinue
    }
    try { Stop-Transcript | Out-Null } catch { }
}
