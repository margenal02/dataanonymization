#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$DistroName = 'Ubuntu-24.04',
    [string]$ProjectPath = $PSScriptRoot,
    [ValidateSet('Auto', 'Store', 'Web')]
    [string]$WslDownloadChannel = 'Auto',
    [ValidateRange(30, 600)]
    [int]$WslNoProgressTimeoutSeconds = 60,
    [switch]$CheckOnly,
    [switch]$AutoReboot,
    [switch]$ResumeAfterRestart
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$script:InstallProgressActive = $false
$script:InstallProgressCells = 0
$MinimumBuild = 19041
$MinimumLogicalProcessors = 8
$RecommendedLogicalProcessors = 12
$MinimumMemoryGB = 16
$RecommendedMemoryGB = 32
$MinimumDiskGB = 50
$RecommendedDiskGB = 80
$MinimumWslVersion = [version]'0.67.6'
$MinimumDockerVersion = '24.0'
$MaximumDockerVersion = '30.0'
$MinimumComposeVersion = '2.20'
$MaximumComposeVersion = '6.0'
$ResumeName = 'DataAnonymizationWslInstaller'
$KeepAliveTaskName = 'DataAnonymizationWslKeepAlive'
$WslBootstrap = @'
#!/usr/bin/env bash
set -Eeuo pipefail

PHASE="${1:-all}"
PROJECT_DIR="${2:-}"
APT_MIRROR="__APT_MIRROR__"
PYPI_MIRROR="__PYPI_MIRROR__"
NPM_MIRROR="__NPM_MIRROR__"
DOCKER_CE_MIRROR="__DOCKER_CE_MIRROR__"
DOCKER_HUB_PREFIX="__DOCKER_HUB_PREFIX__"
DOCKER_REGISTRY_MIRROR="__DOCKER_REGISTRY_MIRROR__"
DOCKER_MIN_VERSION="24.0"
DOCKER_MAX_VERSION="30.0"
COMPOSE_MIN_VERSION="2.20"
COMPOSE_MAX_VERSION="6.0"

log() {
    printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

progress() {
    local percent="$1"
    shift
    local marker
    marker="__DA_PROGRESS__|${percent}|$*"
    printf '%s\n' "$marker"
    if [[ -n "${DA_PROGRESS_FILE:-}" ]]; then
        printf '%s\n' "$marker" >"$DA_PROGRESS_FILE"
    fi
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
    log "配置 Ubuntu 软件源：${APT_MIRROR}"
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
        log "Docker Engine 缺失或低于支持范围，将通过 ${DOCKER_CE_MIRROR} 安装"
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
    if [[ -z "$DOCKER_REGISTRY_MIRROR" ]]; then
        log "未找到可用的 Docker Hub 国内代理，使用 Docker Hub 官方地址"
        return
    fi
    log "配置 Docker Hub 镜像加速：${DOCKER_REGISTRY_MIRROR}"
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
        log "检测到现有 .env，保留密钥和密码并更新镜像地址"
        if grep -Eq '=(please-change-|local-dev-)' "$env_file"; then
            echo "现有 .env 仍含示例弱密钥。请删除它让脚本生成随机密钥，或手工替换示例值。" >&2
            exit 1
        fi
        set_env_value() {
            local key="$1"
            local value="$2"
            if grep -q "^${key}=" "$env_file"; then
                sed -i "s|^${key}=.*|${key}=${value}|" "$env_file"
            else
                printf '%s=%s\n' "$key" "$value" >>"$env_file"
            fi
        }
        set_env_value MYSQL_IMAGE "${DOCKER_HUB_PREFIX}mysql:8.4"
        set_env_value PYTHON_IMAGE "${DOCKER_HUB_PREFIX}python:3.12-slim"
        set_env_value NODE_IMAGE "${DOCKER_HUB_PREFIX}node:22-alpine"
        set_env_value NGINX_IMAGE "${DOCKER_HUB_PREFIX}nginx:1.27-alpine"
        set_env_value PIP_INDEX_URL "$PYPI_MIRROR"
        set_env_value NPM_REGISTRY "$NPM_MIRROR"
        set_env_value DEBIAN_MIRROR "${APT_MIRROR}/debian"
        set_env_value UIE_ENABLED "1"
        set_env_value REQUIRE_HUMAN_REVIEW "1"
        set_env_value UIE_MODEL "uie-base"
        set_env_value UIE_POSITION_PROB "0.45"
        set_env_value UIE_PERSON_PROB "0.70"
        set_env_value UIE_ORGANIZATION_PROB "0.55"
        set_env_value UIE_ADDRESS_PROB "0.60"
        set_env_value UIE_LOCATION_PROB "0.60"
        set_env_value UIE_PRODUCT_PROB "0.60"
        set_env_value UIE_BATCH_SIZE "1"
        set_env_value UIE_MAX_SEQ_LEN "512"
        set_env_value UIE_MAX_TOTAL_CHARS "500000"
        set_env_value UIE_START_TIMEOUT_SECONDS "600"
        set_env_value UIE_REQUEST_TIMEOUT_SECONDS "1800"
        set_env_value PDF_OCR_ENABLED "1"
        set_env_value PDF_OCR_DPI "180"
        set_env_value PDF_OCR_MAX_IMAGE_DIMENSION "3508"
        set_env_value PDF_OCR_MIN_TEXT_CHARS "12"
        set_env_value PDF_OCR_MAX_PAGES "300"
        set_env_value PDF_OCR_MAX_TOTAL_CHARS "500000"
        set_env_value PDF_OCR_PAGE_TIMEOUT_SECONDS "180"
        set_env_value PPSTRUCTURE_DEVICE "cpu"
        set_env_value PPSTRUCTURE_CPU_THREADS "8"
        set_env_value PPSTRUCTURE_LAYOUT_MODEL "PP-DocLayout-S"
        set_env_value PPSTRUCTURE_TEXT_DETECTION_MODEL "PP-OCRv5_mobile_det"
        set_env_value PPSTRUCTURE_TEXT_RECOGNITION_MODEL "PP-OCRv5_mobile_rec"
        set_env_value PPSTRUCTURE_START_TIMEOUT_SECONDS "600"
        sed -i '/^PDF_OCR_LANGUAGES=/d' "$env_file"
        current_upload_limit="$(sed -n 's/^MAX_UPLOAD_SIZE_MB=//p' "$env_file" | tail -n 1 | tr -d '\r')"
        if [[ -z "$current_upload_limit" || "$current_upload_limit" == "50" ]]; then
            set_env_value MAX_UPLOAD_SIZE_MB "200"
            log "上传上限已设置为 200 MB（旧版默认值 50 MB 已自动迁移）"
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
MAX_UPLOAD_SIZE_MB=200
REQUIRE_HUMAN_REVIEW=1
DATA_RETENTION_DAYS=30
MYSQL_IMAGE=${DOCKER_HUB_PREFIX}mysql:8.4
PYTHON_IMAGE=${DOCKER_HUB_PREFIX}python:3.12-slim
NODE_IMAGE=${DOCKER_HUB_PREFIX}node:22-alpine
NGINX_IMAGE=${DOCKER_HUB_PREFIX}nginx:1.27-alpine
PIP_INDEX_URL=${PYPI_MIRROR}
NPM_REGISTRY=${NPM_MIRROR}
DEBIAN_MIRROR=${APT_MIRROR}/debian
UIE_ENABLED=1
UIE_MODEL=uie-base
UIE_POSITION_PROB=0.45
UIE_PERSON_PROB=0.70
UIE_ORGANIZATION_PROB=0.55
UIE_ADDRESS_PROB=0.60
UIE_LOCATION_PROB=0.60
UIE_PRODUCT_PROB=0.60
UIE_BATCH_SIZE=1
UIE_MAX_SEQ_LEN=512
UIE_MAX_TOTAL_CHARS=500000
UIE_START_TIMEOUT_SECONDS=600
UIE_REQUEST_TIMEOUT_SECONDS=1800
PDF_OCR_ENABLED=1
PDF_OCR_DPI=180
PDF_OCR_MAX_IMAGE_DIMENSION=3508
PDF_OCR_MIN_TEXT_CHARS=12
PDF_OCR_MAX_PAGES=300
PDF_OCR_MAX_TOTAL_CHARS=500000
PDF_OCR_PAGE_TIMEOUT_SECONDS=180
PPSTRUCTURE_DEVICE=cpu
PPSTRUCTURE_CPU_THREADS=8
PPSTRUCTURE_LAYOUT_MODEL=PP-DocLayout-S
PPSTRUCTURE_TEXT_DETECTION_MODEL=PP-OCRv5_mobile_det
PPSTRUCTURE_TEXT_RECOGNITION_MODEL=PP-OCRv5_mobile_rec
PPSTRUCTURE_START_TIMEOUT_SECONDS=600
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

run_compose_build() {
    local service="$1"
    local description="$2"
    local build_log="${PROJECT_DIR}/.runtime/docker-build-${service}.log"
    mkdir -p "${PROJECT_DIR}/.runtime"
    : >"$build_log"
    log "${description}；BuildKit 明细实时写入 ${build_log}"
    printf '[%s] 开始构建 %s\n' "$(date '+%F %T')" "$service" | tee -a "$build_log"
    COMPOSE_ANSI=never BUILDKIT_PROGRESS=plain \
        docker compose build "$service" 2>&1 | tee -a "$build_log"
    printf '[%s] %s 构建完成\n' "$(date '+%F %T')" "$service" | tee -a "$build_log"
}

deploy_application() {
    if [[ -z "$PROJECT_DIR" || ! -f "${PROJECT_DIR}/docker-compose.yml" ]]; then
        echo "项目目录无效或缺少 docker-compose.yml：${PROJECT_DIR}" >&2
        exit 1
    fi
    local database_health_result
    progress 2 "步骤 1/11：启动并检查 Docker Engine"
    start_docker
    progress 8 "步骤 2/11：检查并生成安全配置"
    write_secure_environment
    log "使用国内镜像构建并启动数据脱敏应用"
    cd "$PROJECT_DIR"
    progress 15 "步骤 3/11：拉取 MySQL 与 Nginx 基础镜像"
    retry docker compose pull db nginx
    progress 30 "步骤 4/11：构建 Django、PP-StructureV3 精简 OCR 与 UIE-base 后端镜像"
    run_compose_build backend '构建后端：系统依赖 → Python 依赖 → 精简 OCR 与 UIE-base 模型下载、自检'
    progress 48 "步骤 5/11：构建 Vue 前端镜像"
    run_compose_build frontend '构建前端：Node 依赖 → Vue 编译 → Nginx 静态镜像'

    compose_diagnostics() {
        local service="$1"
        local container_id
        container_id="$(docker compose ps -aq "$service" | tail -n 1)"
        printf '\n===== %s 容器诊断 =====\n' "$service" >&2
        if [[ -n "$container_id" ]]; then
            docker inspect --format '状态={{.State.Status}} 退出码={{.State.ExitCode}} 错误={{.State.Error}}' "$container_id" 2>/dev/null || true
            docker inspect --format '{{if .State.Health}}健康={{.State.Health.Status}}{{range .State.Health.Log}}{{println "\n检查时间=" .End " 退出码=" .ExitCode " 输出=" .Output}}{{end}}{{end}}' "$container_id" 2>/dev/null || true
        else
            echo "未找到 ${service} 容器。" >&2
        fi
        docker compose logs --no-color --tail=100 "$service" 2>&1 || true
    }

    database_authentication_failed() {
        local container_id="$1"
        docker inspect --format '{{if .State.Health}}{{range .State.Health.Log}}{{println .Output}}{{end}}{{end}}' \
            "$container_id" 2>/dev/null | grep -q 'ERROR 1045'
    }

    read_env_value() {
        local key="$1"
        sed -n "s/^${key}=//p" "${PROJECT_DIR}/.env" | tail -n 1 | tr -d '\r'
    }

    stop_mysql_repair_container() {
        local container_name="$1"
        docker stop --time 30 "$container_name" >/dev/null 2>&1 || true
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    }

    repair_mysql_credentials() {
        local database_name database_user database_password root_password
        local container_id volume_name database_image repair_container repair_ready attempt

        database_name="$(read_env_value MYSQL_DATABASE)"
        database_user="$(read_env_value MYSQL_USER)"
        database_password="$(read_env_value MYSQL_PASSWORD)"
        root_password="$(read_env_value MYSQL_ROOT_PASSWORD)"

        if [[ ! "$database_name" =~ ^[A-Za-z0-9_]+$ || ! "$database_user" =~ ^[A-Za-z0-9_]+$ ]]; then
            echo "无法自动同步 MySQL 凭据：数据库名或用户名包含不受支持的字符。" >&2
            return 1
        fi
        if [[ ! "$database_password" =~ ^[0-9A-Fa-f]{64}$ || ! "$root_password" =~ ^[0-9A-Fa-f]{64}$ ]]; then
            echo "无法自动同步 MySQL 凭据：仅支持脚本生成的 64 位十六进制随机密码。" >&2
            echo "未修改数据库数据；请按照部署文档的“数据库密码不一致”章节处理。" >&2
            return 1
        fi

        container_id="$(docker compose ps -aq db | tail -n 1)"
        if [[ -z "$container_id" ]]; then
            echo "无法自动同步 MySQL 凭据：未找到 db 容器。" >&2
            return 1
        fi
        volume_name="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}' "$container_id" 2>/dev/null)"
        database_image="$(docker inspect --format '{{.Config.Image}}' "$container_id" 2>/dev/null)"
        if [[ -z "$volume_name" || -z "$database_image" ]]; then
            echo "无法自动同步 MySQL 凭据：未识别到数据库卷或 MySQL 镜像。" >&2
            return 1
        fi

        log "检测到 MySQL 数据卷密码与当前 .env 不一致，开始无损同步账号凭据"
        progress 70 "步骤 7/11：无损同步 MySQL 账号密码（不会删除数据库和任务记录）"
        docker compose stop --timeout 60 db >/dev/null

        repair_container="dataanonymization-mysql-repair"
        stop_mysql_repair_container "$repair_container"
        if ! docker run -d --rm --name "$repair_container" --user mysql \
            --volume "${volume_name}:/var/lib/mysql" --entrypoint mysqld "$database_image" \
            --skip-grant-tables --skip-networking --socket=/tmp/mysql-repair.sock \
            --pid-file=/tmp/mysql-repair.pid --skip-log-bin --general-log=OFF \
            --slow-query-log=OFF >/dev/null; then
            echo "MySQL 临时维护容器启动失败。" >&2
            docker compose up -d db >/dev/null 2>&1 || true
            return 1
        fi

        repair_ready=false
        for attempt in {1..60}; do
            if docker exec "$repair_container" mysqladmin --protocol=socket \
                --socket=/tmp/mysql-repair.sock -uroot ping >/dev/null 2>&1; then
                repair_ready=true
                break
            fi
            if [[ "$(docker inspect --format '{{.State.Running}}' "$repair_container" 2>/dev/null || true)" != "true" ]]; then
                break
            fi
            sleep 1
        done
        if [[ "$repair_ready" != "true" ]]; then
            echo "MySQL 临时维护容器未能就绪。" >&2
            docker logs --tail=80 "$repair_container" >&2 2>&1 || true
            stop_mysql_repair_container "$repair_container"
            docker compose up -d db >/dev/null 2>&1 || true
            return 1
        fi

        if ! printf '%s\n' \
            'FLUSH PRIVILEGES;' \
            "CREATE DATABASE IF NOT EXISTS \`${database_name}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" \
            "CREATE USER IF NOT EXISTS '${database_user}'@'%' IDENTIFIED BY '${database_password}';" \
            "ALTER USER '${database_user}'@'%' IDENTIFIED BY '${database_password}' ACCOUNT UNLOCK;" \
            "GRANT ALL PRIVILEGES ON \`${database_name}\`.* TO '${database_user}'@'%';" \
            "ALTER USER 'root'@'localhost' IDENTIFIED BY '${root_password}';" \
            'FLUSH PRIVILEGES;' | docker exec -i "$repair_container" mysql \
                --protocol=socket --socket=/tmp/mysql-repair.sock -uroot >/dev/null; then
            echo "MySQL 账号凭据同步失败。" >&2
            stop_mysql_repair_container "$repair_container"
            docker compose up -d db >/dev/null 2>&1 || true
            return 1
        fi

        stop_mysql_repair_container "$repair_container"
        docker compose up -d --force-recreate db
        log "MySQL 账号凭据已与当前 .env 同步，数据库内容保持不变"
    }

    wait_for_healthy() {
        local service="$1"
        local maximum_attempts="$2"
        local stage_percent="$3"
        local stage_label="$4"
        local attempt container_id state health
        for ((attempt = 1; attempt <= maximum_attempts; attempt++)); do
            container_id="$(docker compose ps -aq "$service" | tail -n 1)"
            if [[ -z "$container_id" ]]; then
                progress "$stage_percent" "${stage_label}（第 ${attempt}/${maximum_attempts} 次：等待容器创建）"
                sleep 3
                continue
            fi
            state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
            health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
            if [[ "$health" == "healthy" ]]; then
                return 0
            fi
            if [[ "$service" == "db" ]] && database_authentication_failed "$container_id"; then
                progress "$stage_percent" "${stage_label}（检测到 ERROR 1045：数据卷密码与当前 .env 不一致）"
                return 2
            fi
            progress "$stage_percent" "${stage_label}（第 ${attempt}/${maximum_attempts} 次：容器 ${state:-未知}，健康 ${health:-未知}）"
            if [[ "$state" == "exited" || "$state" == "dead" ]]; then
                compose_diagnostics "$service"
                return 1
            fi
            sleep 3
        done
        compose_diagnostics "$service"
        return 1
    }

    log "启动 MySQL 与前端容器"
    progress 62 "步骤 6/11：启动 MySQL 与前端容器"
    stop_mysql_repair_container dataanonymization-mysql-repair
    docker compose up -d --remove-orphans db frontend
    progress 70 "步骤 7/11：等待 MySQL 接受应用账号连接"
    if wait_for_healthy db 60 70 "步骤 7/11：等待 MySQL 接受应用账号连接"; then
        :
    else
        database_health_result=$?
        if [[ "$database_health_result" -eq 2 ]]; then
            if ! repair_mysql_credentials; then
                compose_diagnostics db
                echo "MySQL 密码不一致且无损同步失败；数据库数据未被删除。" >&2
                exit 1
            fi
            if ! wait_for_healthy db 60 70 "步骤 7/11：验证同步后的 MySQL 连接"; then
                compose_diagnostics db
                echo "MySQL 凭据已尝试同步，但容器仍未通过健康检查。" >&2
                exit 1
            fi
        else
            echo "MySQL 容器未能在 180 秒内通过健康检查。" >&2
            exit 1
        fi
    fi

    log "启动并检查 Django 后端容器"
    progress 78 "步骤 8/11：启动 Django 后端容器"
    docker compose up -d --no-deps backend
    progress 85 "步骤 9/11：等待数据库迁移与后端健康检查"
    if ! wait_for_healthy backend 60 85 "步骤 9/11：等待数据库迁移与后端健康检查"; then
        echo "Django 后端容器未能在 180 秒内通过健康检查；诊断信息见上方及安装日志。" >&2
        exit 1
    fi

    log "启动 Nginx 入口容器"
    progress 93 "步骤 10/11：启动 Nginx 入口容器"
    # nginx/default.conf 是只读挂载文件；强制重建才能让正在运行的 Nginx
    # 立即加载新的上传上限和 JSON 错误响应，不要求用户手工重启容器。
    docker compose up -d --no-deps --force-recreate nginx

    log "等待应用健康检查"
    local attempt
    for attempt in {1..60}; do
        progress 97 "步骤 11/11：检查 http://127.0.0.1:5291（第 ${attempt}/60 次）"
        if curl -fsS http://127.0.0.1:5291/api/health/ >/dev/null 2>&1; then
            docker compose ps
            progress 100 "步骤 11/11：应用健康检查通过"
            printf '\n部署成功：http://localhost:5291\n'
            return
        fi
        sleep 3
    done
    docker compose ps -a
    compose_diagnostics backend
    compose_diagnostics nginx
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
    Clear-InstallProgressLine
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

function Write-WslBootstrap([string]$TargetPath, [System.Collections.IDictionary]$MirrorConfig) {
    if (-not $MirrorConfig) { throw '缺少已选择的镜像配置，无法生成 WSL 安装脚本。' }
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    $linuxText = $WslBootstrap -replace "`r`n", "`n"
    $replacements = [ordered]@{
        '__APT_MIRROR__' = [string]$MirrorConfig.AptMirror
        '__PYPI_MIRROR__' = [string]$MirrorConfig.PypiMirror
        '__NPM_MIRROR__' = [string]$MirrorConfig.NpmMirror
        '__DOCKER_CE_MIRROR__' = [string]$MirrorConfig.DockerCeMirror
        '__DOCKER_HUB_PREFIX__' = [string]$MirrorConfig.DockerHubPrefix
        '__DOCKER_REGISTRY_MIRROR__' = [string]$MirrorConfig.DockerRegistryMirror
    }
    foreach ($replacement in $replacements.GetEnumerator()) {
        $linuxText = $linuxText.Replace([string]$replacement.Key, [string]$replacement.Value)
    }
    $unresolvedMirrorTokens = @($replacements.Keys | Where-Object { $linuxText.Contains([string]$_) })
    if ($unresolvedMirrorTokens.Count -gt 0) {
        throw "WSL 安装脚本仍包含未替换的镜像占位符：$($unresolvedMirrorTokens -join ', ')"
    }
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

function ConvertTo-BashSingleQuotedArgument([AllowEmptyString()][string]$Value) {
    if ($null -eq $Value) { $Value = '' }
    return "'" + $Value.Replace("'", "'`"'`"'") + "'"
}

function Register-WslKeepAliveTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Distribution,
        [Parameter(Mandatory = $true)]
        [string]$LinuxProjectPath
    )

    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ([string]::IsNullOrWhiteSpace($currentIdentity)) {
        throw '无法识别当前 Windows 登录账号，不能创建 WSL 常驻任务。'
    }

    $linuxProjectArgument = ConvertTo-BashSingleQuotedArgument $LinuxProjectPath
    $keepAliveCommand = "set -Eeuo pipefail; systemctl start docker; cd $linuxProjectArgument; docker compose up -d; exec /bin/sleep infinity"
    $taskArguments = (@(
        '--distribution', $Distribution,
        '--user', 'root',
        '--', 'bash', '-lc', $keepAliveCommand
    ) | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' '

    $wslExecutable = Join-Path $env:SystemRoot 'System32\wsl.exe'
    try {
        $existingTask = Get-ScheduledTask -TaskName $KeepAliveTaskName -ErrorAction SilentlyContinue
        if ($existingTask) {
            Stop-ScheduledTask -TaskName $KeepAliveTaskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $KeepAliveTaskName -Confirm:$false -ErrorAction Stop
        }

        $action = New-ScheduledTaskAction -Execute $wslExecutable -Argument $taskArguments -ErrorAction Stop
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentIdentity -ErrorAction Stop
        $principal = New-ScheduledTaskPrincipal -UserId $currentIdentity -LogonType Interactive -RunLevel Highest -ErrorAction Stop
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden -MultipleInstances IgnoreNew `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -ErrorAction Stop
        Register-ScheduledTask -TaskName $KeepAliveTaskName -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings `
            -Description '保持数据脱敏应用的 WSL2 与 Docker 容器运行，并在登录 Windows 后自动恢复。' `
            -Force -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $KeepAliveTaskName -ErrorAction Stop

        for ($attempt = 1; $attempt -le 10; $attempt++) {
            Start-Sleep -Milliseconds 500
            $task = Get-ScheduledTask -TaskName $KeepAliveTaskName -ErrorAction SilentlyContinue
            if ($task -and $task.State -eq 'Running') {
                return [pscustomobject]@{
                    Mode = 'ScheduledTask'
                    Active = $true
                    ProcessId = $null
                    Detail = "Windows 登录计划任务 $KeepAliveTaskName"
                }
            }
            if ($task -and $task.State -in @('Disabled', 'Ready')) { break }
        }

        $taskInfo = Get-ScheduledTaskInfo -TaskName $KeepAliveTaskName -ErrorAction SilentlyContinue
        $lastResult = if ($taskInfo) { [string]$taskInfo.LastTaskResult } else { '未知' }
        throw "计划任务未能保持运行（上次结果：$lastResult）"
    } catch {
        $scheduledTaskFailure = $_.Exception.Message
        Write-Warning "Windows 策略不允许创建或启动计划任务，将改用当前登录会话的隐藏后台进程保活。原因：$scheduledTaskFailure"

        try {
            $keepAliveProcess = Start-Process -FilePath $wslExecutable -ArgumentList $taskArguments `
                -WindowStyle Hidden -PassThru -ErrorAction Stop
            Start-Sleep -Seconds 2
            $keepAliveProcess.Refresh()
            if ($keepAliveProcess.HasExited) {
                throw "后台 WSL 进程已退出，退出码为 $($keepAliveProcess.ExitCode)"
            }
            return [pscustomobject]@{
                Mode = 'CurrentSession'
                Active = $true
                ProcessId = $keepAliveProcess.Id
                Detail = "当前 Windows 登录会话后台进程 PID $($keepAliveProcess.Id)"
                ScheduledTaskFailure = $scheduledTaskFailure
            }
        } catch {
            throw "Windows 计划任务创建失败（$scheduledTaskFailure），当前会话后台保活也失败（$($_.Exception.Message)）。"
        }
    }
}

function Wait-WindowsApplicationStable {
    param(
        [int]$RequiredConsecutiveSuccesses = 6,
        [int]$MaximumAttempts = 30
    )

    $addresses = @('http://127.0.0.1:5291/api/health/', 'http://localhost:5291/api/health/')
    $consecutiveSuccesses = 0
    $workingAddress = $null
    for ($attempt = 1; $attempt -le $MaximumAttempts; $attempt++) {
        $healthyThisAttempt = $false
        foreach ($address in $addresses) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri $address -TimeoutSec 5
                if ($response.StatusCode -eq 200) {
                    $healthyThisAttempt = $true
                    $workingAddress = $address
                    break
                }
            } catch { }
        }

        if ($healthyThisAttempt) {
            $consecutiveSuccesses++
        } else {
            $consecutiveSuccesses = 0
        }
        Write-InstallProgress -Percent (95 + [math]::Min(4, $consecutiveSuccesses)) `
            -Activity '验证 Windows 端持续可访问' `
            -Status "稳定检查 $consecutiveSuccesses/$RequiredConsecutiveSuccesses（总检查 $attempt/$MaximumAttempts）"
        if ($consecutiveSuccesses -ge $RequiredConsecutiveSuccesses) {
            Clear-InstallProgressLine
            return [pscustomobject]@{
                Healthy = $true
                Address = $workingAddress
            }
        }
        Start-Sleep -Seconds 3
    }

    Clear-InstallProgressLine
    return [pscustomobject]@{
        Healthy = $false
        Address = $null
    }
}

function Write-InstallProgress {
    param(
        [ValidateRange(0, 100)]
        [int]$Percent,
        [string]$Activity,
        [string]$Status = '',
        [switch]$CompleteLine
    )

    $barWidth = 20
    $filled = [math]::Floor($Percent * $barWidth / 100)
    $bar = ('#' * $filled) + ('-' * ($barWidth - $filled))
    $detail = if ([string]::IsNullOrWhiteSpace($Status)) { $Activity } else { "$Activity - $Status" }
    $line = "[$bar] $($Percent.ToString().PadLeft(3))%  $detail"
    $bufferWidth = try { [math]::Max(2, [Console]::BufferWidth) } catch { 100 }
    $maximumCells = [math]::Max(1, $bufferWidth - 1)
    $line = Limit-ConsoleText -Text $line -MaximumCells $maximumCells
    $lineCells = Get-ConsoleTextWidth $line
    $eraseCells = [math]::Max($script:InstallProgressCells, $lineCells)
    Write-Host ("`r" + $line + (' ' * ($eraseCells - $lineCells)) + "`r") -NoNewline -ForegroundColor Cyan
    $script:InstallProgressActive = $true
    $script:InstallProgressCells = $lineCells
    if ($CompleteLine) {
        Clear-InstallProgressLine
        Write-Host ("[{0,3}%] {1}" -f $Percent, $detail) -ForegroundColor Cyan
    }
}

function Get-ConsoleTextWidth([string]$Text) {
    $width = 0
    foreach ($character in $Text.ToCharArray()) {
        $code = [int]$character
        $width += if ($code -le 0x7F) { 1 } else { 2 }
    }
    return $width
}

function Limit-ConsoleText([string]$Text, [int]$MaximumCells) {
    if ($MaximumCells -le 0) { return '' }
    $builder = New-Object Text.StringBuilder
    $cells = 0
    foreach ($character in $Text.ToCharArray()) {
        $characterCells = if ([int]$character -le 0x7F) { 1 } else { 2 }
        if (($cells + $characterCells) -gt $MaximumCells) { break }
        $null = $builder.Append($character)
        $cells += $characterCells
    }
    return $builder.ToString()
}

function Clear-InstallProgressLine {
    if (-not $script:InstallProgressActive) { return }
    $bufferWidth = try { [math]::Max(2, [Console]::BufferWidth) } catch { 100 }
    $clearCells = [math]::Min([math]::Max($script:InstallProgressCells, 1), $bufferWidth - 1)
    Write-Host ("`r" + (' ' * $clearCells) + "`r") -NoNewline
    $script:InstallProgressActive = $false
    $script:InstallProgressCells = 0
}

function Invoke-SystemProbeWithTimeout {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$ScriptBlock,
        [object[]]$ArgumentList = @(),
        [ValidateRange(1, 120)]
        [int]$TimeoutSeconds = 15,
        [ValidateRange(1, 20)]
        [int]$StepNumber,
        [ValidateRange(1, 20)]
        [int]$StepCount,
        [ValidateRange(0, 10)]
        [int]$ProgressPercent
    )

    $activity = "系统检测 $StepNumber/$StepCount：$Name"
    Write-InstallProgress -Percent $ProgressPercent -Activity $activity `
        -Status "开始（最长等待 $TimeoutSeconds 秒）" -CompleteLine

    $job = $null
    try {
        $job = Start-Job -ScriptBlock $ScriptBlock -ArgumentList $ArgumentList
        $completedJob = Wait-Job -Job $job -Timeout $TimeoutSeconds
        if (-not $completedJob) {
            throw "系统检测 [$Name] 超过 $TimeoutSeconds 秒无响应，已停止。请检查 WMI、DISM 或网络服务状态。"
        }
        if ($job.State -ne 'Completed') {
            $reason = $job.ChildJobs[0].JobStateInfo.Reason
            $reasonText = if ($reason) { $reason.Message } else { "任务状态为 $($job.State)" }
            throw "系统检测 [$Name] 未正常完成：$reasonText"
        }

        $output = @(Receive-Job -Job $job -ErrorAction Stop)
        Write-InstallProgress -Percent $ProgressPercent -Activity $activity -Status '完成' -CompleteLine
        if ($output.Count -eq 1) { return $output[0] }
        return $output
    }
    catch {
        Write-InstallProgress -Percent $ProgressPercent -Activity $activity `
            -Status "失败：$($_.Exception.Message)" -CompleteLine
        throw
    }
    finally {
        if ($job) {
            if ($job.State -in @('Running', 'NotStarted')) {
                Stop-Job -Job $job -ErrorAction SilentlyContinue
            }
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
    }
}

function ConvertFrom-NativeBytes([byte[]]$Bytes) {
    if (-not $Bytes -or $Bytes.Length -eq 0) { return '' }
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) {
        return [Text.Encoding]::Unicode.GetString($Bytes, 2, $Bytes.Length - 2)
    }
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFE -and $Bytes[1] -eq 0xFF) {
        return [Text.Encoding]::BigEndianUnicode.GetString($Bytes, 2, $Bytes.Length - 2)
    }
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        return [Text.Encoding]::UTF8.GetString($Bytes, 3, $Bytes.Length - 3)
    }

    $sampleLength = [math]::Min($Bytes.Length, 4096)
    $evenNulls = 0
    $oddNulls = 0
    for ($index = 0; $index -lt $sampleLength; $index++) {
        if ($Bytes[$index] -eq 0) {
            if (($index % 2) -eq 0) { $evenNulls++ } else { $oddNulls++ }
        }
    }
    if ($oddNulls -gt ($sampleLength / 8)) { return [Text.Encoding]::Unicode.GetString($Bytes) }
    if ($evenNulls -gt ($sampleLength / 8)) { return [Text.Encoding]::BigEndianUnicode.GetString($Bytes) }

    try {
        $strictUtf8 = New-Object Text.UTF8Encoding($false, $true)
        return $strictUtf8.GetString($Bytes)
    } catch {
        return [Text.Encoding]::Default.GetString($Bytes)
    }
}

function Read-NativeOutputFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $bytes = New-Object byte[] $stream.Length
        $null = $stream.Read($bytes, 0, $bytes.Length)
        return ConvertFrom-NativeBytes $bytes
    } finally {
        $stream.Dispose()
    }
}

function Read-NativeOutputTail([string]$Path, [int]$MaximumBytes = 524288) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $length = [long]$stream.Length
        $bytesToRead = [int][math]::Min($length, [math]::Max(1, $MaximumBytes))
        $isTail = $length -gt $bytesToRead
        if ($isTail) { $null = $stream.Seek(-$bytesToRead, [IO.SeekOrigin]::End) }
        $bytes = New-Object byte[] $bytesToRead
        $actual = $stream.Read($bytes, 0, $bytes.Length)
        if ($actual -le 0) { return '' }
        if ($actual -lt $bytes.Length) { $bytes = $bytes[0..($actual - 1)] }
        if ($isTail) {
            $skip = 0
            while ($skip -lt [math]::Min(3, $bytes.Length) -and (($bytes[$skip] -band 0xC0) -eq 0x80)) { $skip++ }
            if ($skip -gt 0 -and $skip -lt $bytes.Length) { $bytes = $bytes[$skip..($bytes.Length - 1)] }
        }
        return ConvertFrom-NativeBytes $bytes
    } finally {
        $stream.Dispose()
    }
}

function Get-NativePercent([string[]]$Paths) {
    $latestPercent = $null
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            $text = Read-NativeOutputFile $path
            if ([string]::IsNullOrEmpty($text)) { continue }
            foreach ($match in [regex]::Matches($text, '(?<!\d)(100|[0-9]{1,2})(?:\.[0-9]+)?\s*%')) {
                $value = [int][math]::Floor([double]$match.Groups[1].Value)
                if ($value -ge 0 -and $value -le 100) { $latestPercent = $value }
            }
        } catch {
            # 文件可能正在被子进程写入；下一轮继续读取。
        }
    }
    return $latestPercent
}

function Get-NativeProgressState([string[]]$Paths) {
    $latestMarkerPercent = $null
    $latestMarkerStatus = $null
    $latestOutput = $null
    $latestPlainPercent = $null
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        try {
            # Docker build logs can grow to many megabytes. Only inspect the tail on
            # each refresh; the caller keeps the most recent structured marker.
            $text = Read-NativeOutputTail $path
            if ([string]::IsNullOrWhiteSpace($text)) { continue }
            foreach ($match in [regex]::Matches($text, '(?m)^__DA_PROGRESS__\|(100|[0-9]{1,2})\|([^\r\n]*)')) {
                $latestMarkerPercent = [int]$match.Groups[1].Value
                $latestMarkerStatus = $match.Groups[2].Value.Trim()
            }
            foreach ($match in [regex]::Matches($text, '(?<!\d)(100|[0-9]{1,2})(?:\.[0-9]+)?\s*%')) {
                $value = [int][math]::Floor([double]$match.Groups[1].Value)
                if ($value -ge 0 -and $value -le 100) { $latestPlainPercent = $value }
            }
            foreach ($line in @($text -split "`r?`n")) {
                $clean = [regex]::Replace([string]$line, "$([char]27)\[[0-?]*[ -/]*[@-~]", '')
                $clean = ($clean -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', '').Trim()
                if ([string]::IsNullOrWhiteSpace($clean) -or $clean -match '^__DA_PROGRESS__\|') { continue }
                if ($clean -match '(?i)(PASSWORD|SECRET_KEY|ENCRYPTION_KEY)\s*=') { continue }
                $latestOutput = $clean
            }
        } catch {
            # 子进程可能正在写入；下一轮重新读取。
        }
    }
    $percent = if ($null -ne $latestMarkerPercent) { $latestMarkerPercent } else { $latestPlainPercent }
    return [pscustomobject]@{
        Percent = $percent
        Status = $latestMarkerStatus
        LatestOutput = $latestOutput
        HasMarker = $null -ne $latestMarkerPercent
    }
}

function Format-Elapsed([TimeSpan]$Elapsed) {
    if ($Elapsed.TotalHours -ge 1) { return ('{0:00}:{1:00}:{2:00}' -f [int]$Elapsed.TotalHours, $Elapsed.Minutes, $Elapsed.Seconds) }
    return ('{0:00}:{1:00}' -f [int]$Elapsed.TotalMinutes, $Elapsed.Seconds)
}

function Stop-NativeProcessTree([System.Diagnostics.Process]$Process) {
    if (-not $Process) { return }
    try {
        if (-not $Process.HasExited) {
            # Windows PowerShell 5.1/.NET Framework 没有 Process.Kill(true)，
            # 使用 taskkill 只结束本次启动的 cmd 及其 WSL 子进程。
            & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
            if (-not $Process.WaitForExit(5000)) { $Process.Kill() }
        }
    } catch {
        try { if (-not $Process.HasExited) { $Process.Kill() } } catch { }
    }
}

function Invoke-NativeCommandWithProgress {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$Activity = '正在执行',
        [ValidateRange(0, 100)]
        [int]$ProgressStart = 0,
        [ValidateRange(0, 100)]
        [int]$ProgressEnd = 100,
        [ValidateRange(0, 3600)]
        [int]$NoProgressTimeoutSeconds = 0,
        [ValidateRange(0, 3600)]
        [int]$CommandTimeoutSeconds = 0,
        [string]$ProgressStatePath = '',
        [switch]$SuppressFailureOutput
    )

    if ($ProgressEnd -lt $ProgressStart) { throw '进度结束值不能小于起始值。' }
    $stdoutPath = [IO.Path]::GetTempFileName()
    $stderrPath = [IO.Path]::GetTempFileName()
    if (-not [string]::IsNullOrWhiteSpace($ProgressStatePath)) {
        Remove-Item -LiteralPath $ProgressStatePath -Force -ErrorAction SilentlyContinue
    }
    $argumentText = (($ArgumentList | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' ')
    Write-InstallProgress -Percent $ProgressStart -Activity $Activity -Status '正在启动子进程（已等待 00:00）'
    $resolvedCommand = Get-Command $FilePath -ErrorAction Stop
    $nativePath = if ($resolvedCommand.Source) { $resolvedCommand.Source } else { $FilePath }
    $redirectedCommand = '{0} {1} 1>{2} 2>{3}' -f `
        (ConvertTo-NativeArgument $nativePath),
        $argumentText,
        (ConvertTo-NativeArgument $stdoutPath),
        (ConvertTo-NativeArgument $stderrPath)
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $env:ComSpec
    $startInfo.Arguments = '/d /s /c "' + $redirectedCommand + '"'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        try {
            if (-not $process.Start()) { throw "无法启动：$FilePath" }
            $lastShown = -1
            $lastNativePercent = -1
            $lastProgressAt = [DateTime]::UtcNow
            $startedAt = [DateTime]::UtcNow
            $lastDisplayAt = [DateTime]::MinValue
            $lastDisplayText = ''
            $nativePercent = $null
            $markerPercent = $null
            $markerStatus = $null
            $markerStepKey = ''
            $stepStartedAt = $startedAt
            $latestOutput = $null
            $timedOut = $false
            $timeoutStatus = ''
            while (-not $process.WaitForExit(250)) {
                $now = [DateTime]::UtcNow
                if (($now - $lastDisplayAt).TotalSeconds -ge 1) {
                    $progressPaths = @($stdoutPath, $stderrPath)
                    if (-not [string]::IsNullOrWhiteSpace($ProgressStatePath)) { $progressPaths += $ProgressStatePath }
                    $nativeState = Get-NativeProgressState $progressPaths
                    if ($nativeState.HasMarker) {
                        $markerPercent = $nativeState.Percent
                        $markerStatus = $nativeState.Status
                        $newStepKey = if ($markerStatus -match '^(步骤\s+\d+/\d+)') { $Matches[1] } else { $markerStatus }
                        if ($newStepKey -ne $markerStepKey) {
                            $markerStepKey = $newStepKey
                            $stepStartedAt = $now
                        }
                    }
                    if (-not [string]::IsNullOrWhiteSpace($nativeState.LatestOutput)) {
                        $latestOutput = $nativeState.LatestOutput
                    }
                    $nativePercent = if ($null -ne $markerPercent) { $markerPercent } else { $nativeState.Percent }
                    if ($null -ne $nativePercent -and $nativePercent -gt $lastNativePercent) {
                        $lastNativePercent = $nativePercent
                        $lastProgressAt = $now
                    }
                }
                if ($null -ne $nativePercent) {
                    $overallPercent = $ProgressStart + [math]::Floor(
                        ($ProgressEnd - $ProgressStart) * $nativePercent / 100
                    )
                } else {
                    $overallPercent = $ProgressStart
                }
                if (($now - $lastDisplayAt).TotalSeconds -ge 1) {
                    $elapsedText = Format-Elapsed ($now - $startedAt)
                    $stepElapsedText = Format-Elapsed ($now - $stepStartedAt)
                    if (-not [string]::IsNullOrWhiteSpace($markerStatus)) {
                        $statusText = "$markerStatus；本步骤 $stepElapsedText；总计 $elapsedText"
                    } elseif ($null -ne $nativePercent) {
                        $statusText = "当前阶段 $nativePercent%；已等待 $elapsedText"
                    } else {
                        $statusText = "子进程正在运行；已等待 $elapsedText"
                    }
                    if (-not [string]::IsNullOrWhiteSpace($latestOutput) -and $latestOutput -ne $markerStatus) {
                        $statusText += "；最近：$latestOutput"
                    }
                    if ($statusText -ne $lastDisplayText -or $overallPercent -ne $lastShown) {
                        Write-InstallProgress -Percent $overallPercent -Activity $Activity -Status $statusText
                        $lastDisplayText = $statusText
                        $lastShown = $overallPercent
                    }
                    $lastDisplayAt = $now
                }
                if ($CommandTimeoutSeconds -gt 0 -and
                    ($now - $startedAt).TotalSeconds -ge $CommandTimeoutSeconds) {
                    $timedOut = $true
                    $timeoutStatus = "超过 $CommandTimeoutSeconds 秒无响应，已停止"
                    Write-InstallProgress -Percent $ProgressStart -Activity $Activity -Status $timeoutStatus
                    Stop-NativeProcessTree $process
                    break
                }
                if ($NoProgressTimeoutSeconds -gt 0 -and $lastNativePercent -lt 100 -and
                    ($now - $lastProgressAt).TotalSeconds -ge $NoProgressTimeoutSeconds) {
                    $timedOut = $true
                    $timeoutStatus = "连续 $NoProgressTimeoutSeconds 秒无真实下载进展，正在切换通道"
                    Write-InstallProgress -Percent $ProgressStart -Activity $Activity `
                        -Status $timeoutStatus
                    Stop-NativeProcessTree $process
                    break
                }
            }
            if (-not $timedOut) { $process.WaitForExit() }
            $exitCode = if ($timedOut) { -1 } else { $process.ExitCode }
            $capturedOutput = @()
            foreach ($path in @($stdoutPath, $stderrPath)) {
                if (Test-Path -LiteralPath $path) {
                    $decoded = Read-NativeOutputFile $path
                    if (-not [string]::IsNullOrWhiteSpace($decoded)) {
                        $capturedOutput += @($decoded -split "`r?`n")
                    }
                }
            }
            $resultStatus = if ($timedOut) { $timeoutStatus } elseif ($exitCode -eq 0) { '完成' } else { '失败' }
            Write-InstallProgress -Percent $(if ($exitCode -eq 0) { $ProgressEnd } else { $ProgressStart }) `
                -Activity $Activity -Status $resultStatus -CompleteLine
            if ($exitCode -ne 0 -and -not $SuppressFailureOutput) {
                Clear-InstallProgressLine
                $capturedOutput | Where-Object { $_ -notmatch '^__DA_PROGRESS__\|' } |
                    Select-Object -Last 120 | ForEach-Object { Write-Host ([string]$_) }
            }
            return [pscustomobject]@{
                Output = $capturedOutput
                ExitCode = $exitCode
                TimedOut = $timedOut
                TimeoutStatus = $timeoutStatus
            }
        } catch [System.Management.Automation.PipelineStoppedException] {
            Stop-NativeProcessTree $process
            throw
        }
    } finally {
        if ($process) { $process.Dispose() }
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($ProgressStatePath)) {
            Remove-Item -LiteralPath $ProgressStatePath -Force -ErrorAction SilentlyContinue
        }
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
        [ValidateRange(0, 100)]
        [int]$ProgressStart = 0,
        [ValidateRange(0, 100)]
        [int]$ProgressEnd = 100,
        [ValidateRange(0, 3600)]
        [int]$NoProgressTimeoutSeconds = 0,
        [ValidateRange(0, 3600)]
        [int]$CommandTimeoutSeconds = 0,
        [string]$ProgressStatePath = ''
    )

    if ($DisplayOutput) {
        return Invoke-NativeCommandWithProgress -FilePath $FilePath -ArgumentList $ArgumentList `
            -Activity $Activity -ProgressStart $ProgressStart -ProgressEnd $ProgressEnd `
            -NoProgressTimeoutSeconds $NoProgressTimeoutSeconds -CommandTimeoutSeconds $CommandTimeoutSeconds `
            -ProgressStatePath $ProgressStatePath `
            -SuppressFailureOutput:$IgnoreStandardError
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

function Get-LastNonEmptyNativeOutput($Result) {
    if ($null -eq $Result -or $null -eq $Result.Output) { return $null }
    $lastLine = @($Result.Output | ForEach-Object {
        ([string]($_ -replace "`0", '')).Trim()
    } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 1)
    if ($lastLine.Count -eq 0) { return $null }
    return [string]$lastLine[0]
}

function ConvertTo-WslPath([string]$Distribution, [string]$WindowsPath) {
    $result = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $Distribution, '--user', 'root', '--', 'wslpath', '-a', '-u', $WindowsPath) `
        -IgnoreStandardError
    $convertedPath = Get-LastNonEmptyNativeOutput $result
    if ($result.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($convertedPath)) {
        return $convertedPath
    }

    # A newly installed WSL distribution can occasionally return exit code 0 but
    # no captured wslpath output. Fall back only for a normal local drive path,
    # then ask the target distribution to verify the resulting mount path.
    if ($WindowsPath -match '^([A-Za-z]):[\\/]*(.*)$') {
        $drive = $Matches[1].ToLowerInvariant()
        $relativePath = $Matches[2] -replace '\\', '/'
        $fallbackPath = if ([string]::IsNullOrWhiteSpace($relativePath)) {
            "/mnt/$drive"
        } else {
            "/mnt/$drive/$relativePath"
        }
        $validation = Invoke-NativeCommand -FilePath 'wsl.exe' `
            -ArgumentList @('--distribution', $Distribution, '--user', 'root', '--', 'test', '-e', $fallbackPath) `
            -IgnoreStandardError
        if ($validation.ExitCode -eq 0) {
            Write-Warning "wslpath 未返回结果，已验证并使用标准 WSL 挂载路径：$fallbackPath"
            return $fallbackPath
        }
    }

    $exitDescription = if ($null -eq $result) { '无执行结果' } else { "退出码 $($result.ExitCode)" }
    throw "无法把 Windows 路径转换为 WSL 路径（$exitDescription）：$WindowsPath"
}

function Get-WslRuntimeVersion(
    [switch]$ShowDetectionProgress,
    [int]$ProgressStart = 10,
    [int]$ProgressEnd = 13,
    [string]$Activity = '检测 WSL 运行时版本'
) {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return $null }
    if ($ShowDetectionProgress) {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--version') -IgnoreStandardError `
            -DisplayOutput -Activity $Activity -ProgressStart $ProgressStart -ProgressEnd $ProgressEnd `
            -CommandTimeoutSeconds 12
    } else {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--version') -IgnoreStandardError
    }
    if ($result.ExitCode -ne 0) { return $null }
    foreach ($line in $result.Output) {
        $cleanLine = [string]($line -replace "`0", '')
        if ($cleanLine -match '(\d+\.\d+(?:\.\d+){0,2})') {
            try { return [version]$Matches[1] } catch { return $null }
        }
    }
    return $null
}

function Get-InstalledWslDistros(
    [switch]$ShowDetectionProgress,
    [int]$ProgressStart = 13,
    [int]$ProgressEnd = 16,
    [string]$Activity = '检测已安装的 WSL 发行版'
) {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return @() }
    if ($ShowDetectionProgress) {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--list', '--quiet') -IgnoreStandardError `
            -DisplayOutput -Activity $Activity -ProgressStart $ProgressStart -ProgressEnd $ProgressEnd `
            -CommandTimeoutSeconds 12
    } else {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--list', '--quiet') -IgnoreStandardError
    }
    if ($result.ExitCode -ne 0) { return @() }
    return @($result.Output | ForEach-Object {
        ([string]($_ -replace "`0", '')).Trim().TrimStart('*').Trim()
    } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-WslDistroGeneration([string]$Name, [switch]$ShowDetectionProgress) {
    $lxssPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
    if (Test-Path $lxssPath) {
        foreach ($key in @(Get-ChildItem -Path $lxssPath -ErrorAction SilentlyContinue)) {
            $properties = Get-ItemProperty -Path $key.PSPath -ErrorAction SilentlyContinue
            if ($properties.DistributionName -eq $Name -and [int]$properties.Version -in @(1, 2)) {
                if ($ShowDetectionProgress) {
                    Write-InstallProgress -Percent 18 -Activity "检测 $Name 的 WSL 版本" `
                        -Status '从系统注册信息读取完成' -CompleteLine
                }
                return [int]$properties.Version
            }
        }
    }

    $escapedName = [regex]::Escape($Name)
    if ($ShowDetectionProgress) {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--list', '--verbose') -IgnoreStandardError `
            -DisplayOutput -Activity "检测 $Name 的 WSL 版本" -ProgressStart 16 -ProgressEnd 18 `
            -CommandTimeoutSeconds 12
    } else {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--list', '--verbose') -IgnoreStandardError
    }
    foreach ($line in $result.Output) {
        $cleanLine = [string]($line -replace "`0", '')
        if ($cleanLine -match "^\s*\*?\s*$escapedName\s+\S+\s+([12])\s*$") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Get-WslDockerVersions([string]$Name, [int]$Generation, [switch]$ShowDetectionProgress) {
    $state = [ordered]@{ Docker = $null; Compose = $null }
    if ($Generation -ne 2) { return [pscustomobject]$state }
    $command = 'docker_version=$(docker --version 2>/dev/null | sed -nE "s/.*version ([0-9]+(\.[0-9]+){1,3}).*/\1/p"); compose_version=$(docker compose version --short 2>/dev/null | sed -nE "s/^v?([0-9]+(\.[0-9]+){1,3}).*/\1/p"); printf "%s|%s\n" "$docker_version" "$compose_version"'
    if ($ShowDetectionProgress) {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' `
            -ArgumentList @('--distribution', $Name, '--user', 'root', '--', 'bash', '-lc', $command) `
            -IgnoreStandardError -DisplayOutput -Activity '检测 Docker 与 Compose 版本' `
            -ProgressStart 18 -ProgressEnd 20 -CommandTimeoutSeconds 20
    } else {
        $result = Invoke-NativeCommand -FilePath 'wsl.exe' `
            -ArgumentList @('--distribution', $Name, '--user', 'root', '--', 'bash', '-lc', $command) `
            -IgnoreStandardError
    }
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

function Format-ByteSize([long]$Bytes) {
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }
    return ('{0:N1} KB' -f ($Bytes / 1KB))
}

function Select-FastestWslMsiUri([string]$OfficialUri) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        return [pscustomobject]@{ Name = 'GitHub 官方直连'; Uri = $OfficialUri; Mbps = 0 }
    }

    $candidates = @(
        [pscustomobject]@{ Name = 'GitHub 官方直连'; Uri = $OfficialUri },
        [pscustomobject]@{ Name = 'gh-proxy.com 大陆加速传输'; Uri = "https://gh-proxy.com/$OfficialUri" },
        [pscustomobject]@{ Name = 'ghfast.top 大陆加速传输'; Uri = "https://ghfast.top/$OfficialUri" }
    )
    $results = @()
    Write-Host '正在对 WSL MSI 下载通道进行 1 MB 实际测速……' -ForegroundColor Cyan
    foreach ($candidate in $candidates) {
        $probePath = [IO.Path]::GetTempFileName()
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $probeProcess = $null
        try {
            $probeArguments = @(
                '--location', '--fail', '--silent', '--show-error',
                '--connect-timeout', '5', '--max-time', '12', '--range', '0-1048575',
                '--user-agent', 'DataAnonymization-WSL-Installer/1.0',
                '--output', $probePath, $candidate.Uri
            )
            $probeInfo = New-Object Diagnostics.ProcessStartInfo
            $probeInfo.FileName = $curl.Source
            $probeInfo.Arguments = (($probeArguments | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' ')
            $probeInfo.UseShellExecute = $false
            $probeInfo.CreateNoWindow = $true
            $probeInfo.RedirectStandardError = $true
            $probeProcess = New-Object Diagnostics.Process
            $probeProcess.StartInfo = $probeInfo
            if (-not $probeProcess.Start()) { throw '无法启动测速进程。' }
            while (-not $probeProcess.WaitForExit(100)) {
                $currentLength = if (Test-Path -LiteralPath $probePath) {
                    [long](Get-Item -LiteralPath $probePath).Length
                } else {
                    0L
                }
                if ($currentLength -ge 1MB) {
                    Stop-NativeProcessTree $probeProcess
                    break
                }
            }
            $watch.Stop()
            $length = if (Test-Path -LiteralPath $probePath) { [long](Get-Item -LiteralPath $probePath).Length } else { 0L }
            $header = if ($length -ge 8) { [IO.File]::ReadAllBytes($probePath)[0..7] } else { @() }
            $isMsi = $header.Count -eq 8 -and
                (($header | ForEach-Object { $_.ToString('X2') }) -join '') -eq 'D0CF11E0A1B11AE1'
            if ($isMsi -and $length -ge 65536) {
                $mbps = ($length / 1MB) / [math]::Max($watch.Elapsed.TotalSeconds, 0.001)
                $results += [pscustomobject]@{ Name = $candidate.Name; Uri = $candidate.Uri; Mbps = $mbps }
                Write-Host ("  {0}：{1:N2} MB/s" -f $candidate.Name, $mbps) -ForegroundColor Gray
            } else {
                Write-Host ("  {0}：不可用或未返回有效 MSI" -f $candidate.Name) -ForegroundColor DarkGray
            }
        } catch {
            $watch.Stop()
            Write-Host ("  {0}：测速失败" -f $candidate.Name) -ForegroundColor DarkGray
        } finally {
            if ($probeProcess) { $probeProcess.Dispose() }
            Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
        }
    }
    if ($results.Count -eq 0) {
        Write-Warning '测速通道均未完成 1 MB 有效 MSI 取样，回退 GitHub 官方直连。'
        return [pscustomobject]@{ Name = 'GitHub 官方直连'; Uri = $OfficialUri; Mbps = 0 }
    }
    $selected = $results | Sort-Object Mbps -Descending | Select-Object -First 1
    Write-Host ("选择最快通道：{0}（测速 {1:N2} MB/s）" -f $selected.Name, $selected.Mbps) -ForegroundColor Green
    return $selected
}

function Invoke-DotNetFileDownloadWithProgress {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [string]$Activity,
        [int]$ProgressStart,
        [int]$ProgressEnd,
        [long]$ExpectedSize = -1
    )

    $partialPath = "$Destination.part"
    $destinationDirectory = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null

    $totalBytes = $ExpectedSize
    if ($totalBytes -le 0) {
        $head = [Net.HttpWebRequest]::Create($Uri)
        $head.Method = 'HEAD'
        $head.UserAgent = 'DataAnonymization-WSL-Installer/1.0'
        $head.AllowAutoRedirect = $true
        $head.Timeout = 15000
        $head.ReadWriteTimeout = 15000
        try {
            $headResponse = $head.GetResponse()
            try { $totalBytes = [long]$headResponse.ContentLength } finally { $headResponse.Dispose() }
        } catch {
            $totalBytes = -1
        }
    }

    if ((Test-Path -LiteralPath $Destination) -and $totalBytes -gt 0 -and
        (Get-Item -LiteralPath $Destination).Length -eq $totalBytes) {
        Write-InstallProgress -Percent $ProgressEnd -Activity $Activity `
            -Status ("已缓存 {0}，跳过下载" -f (Format-ByteSize $totalBytes)) -CompleteLine
        return $Destination
    }
    if ((Test-Path -LiteralPath $partialPath) -and $totalBytes -gt 0 -and
        (Get-Item -LiteralPath $partialPath).Length -eq $totalBytes) {
        Move-Item -LiteralPath $partialPath -Destination $Destination -Force
        Write-InstallProgress -Percent $ProgressEnd -Activity $Activity `
            -Status ("断点文件已完整，恢复缓存 {0}" -f (Format-ByteSize $totalBytes)) -CompleteLine
        return $Destination
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $existingBytes = if (Test-Path -LiteralPath $partialPath) {
            [long](Get-Item -LiteralPath $partialPath).Length
        } else {
            0L
        }
        if ($totalBytes -gt 0 -and $existingBytes -gt $totalBytes) {
            Remove-Item -LiteralPath $partialPath -Force
            $existingBytes = 0L
        }

        $request = [Net.HttpWebRequest]::Create($Uri)
        $request.Method = 'GET'
        $request.UserAgent = 'DataAnonymization-WSL-Installer/1.0'
        $request.AllowAutoRedirect = $true
        $request.Timeout = 30000
        $request.ReadWriteTimeout = 30000
        if ($existingBytes -gt 0) { $request.AddRange($existingBytes) }

        $response = $null
        $networkStream = $null
        $fileStream = $null
        try {
            $response = $request.GetResponse()
            $isPartial = [int]$response.StatusCode -eq 206
            if ($existingBytes -gt 0 -and -not $isPartial) {
                $existingBytes = 0L
                Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
            }
            if ($totalBytes -le 0) {
                $totalBytes = if ($isPartial) {
                    $existingBytes + [long]$response.ContentLength
                } else {
                    [long]$response.ContentLength
                }
            }

            $fileMode = if ($existingBytes -gt 0 -and $isPartial) {
                [IO.FileMode]::Append
            } else {
                [IO.FileMode]::Create
            }
            $fileStream = New-Object IO.FileStream($partialPath, $fileMode, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            $networkStream = $response.GetResponseStream()
            $buffer = New-Object byte[] (1MB)
            $downloadedBytes = $existingBytes
            $startedAt = [DateTime]::UtcNow
            $sampleAt = $startedAt
            $sampleBytes = $downloadedBytes
            $lastDisplayAt = [DateTime]::MinValue

            while ($true) {
                $asyncRead = $networkStream.BeginRead($buffer, 0, $buffer.Length, $null, $null)
                while (-not $asyncRead.AsyncWaitHandle.WaitOne(500)) {
                    $now = [DateTime]::UtcNow
                    $averageSeconds = [math]::Max(($now - $startedAt).TotalSeconds, 0.001)
                    $averageMbps = (($downloadedBytes - $existingBytes) / 1MB) / $averageSeconds
                    if ($totalBytes -gt 0) {
                        $filePercent = [math]::Min(100, [math]::Floor($downloadedBytes * 100 / $totalBytes))
                        $overall = $ProgressStart + [math]::Floor(($ProgressEnd - $ProgressStart) * $filePercent / 100)
                        $sizeText = "$(Format-ByteSize $downloadedBytes) / $(Format-ByteSize $totalBytes)"
                    } else {
                        $filePercent = 0
                        $overall = $ProgressStart
                        $sizeText = Format-ByteSize $downloadedBytes
                    }
                    $status = "$filePercent%｜$sizeText｜实时 0.00 MB/s｜平均 {0:N2} MB/s" -f $averageMbps
                    Write-InstallProgress -Percent $overall -Activity $Activity -Status $status
                    $sampleAt = $now
                    $sampleBytes = $downloadedBytes
                    $lastDisplayAt = $now
                }
                $read = $networkStream.EndRead($asyncRead)
                $asyncRead.AsyncWaitHandle.Dispose()
                if ($read -le 0) { break }
                $fileStream.Write($buffer, 0, $read)
                $downloadedBytes += $read
                $now = [DateTime]::UtcNow
                if (($now - $lastDisplayAt).TotalMilliseconds -ge 500) {
                    $sampleSeconds = [math]::Max(($now - $sampleAt).TotalSeconds, 0.001)
                    $instantMbps = (($downloadedBytes - $sampleBytes) / 1MB) / $sampleSeconds
                    $averageSeconds = [math]::Max(($now - $startedAt).TotalSeconds, 0.001)
                    $averageMbps = (($downloadedBytes - $existingBytes) / 1MB) / $averageSeconds
                    if ($totalBytes -gt 0) {
                        $filePercent = [math]::Min(100, [math]::Floor($downloadedBytes * 100 / $totalBytes))
                        $overall = $ProgressStart + [math]::Floor(($ProgressEnd - $ProgressStart) * $filePercent / 100)
                        $sizeText = "$(Format-ByteSize $downloadedBytes) / $(Format-ByteSize $totalBytes)"
                    } else {
                        $filePercent = 0
                        $overall = $ProgressStart
                        $sizeText = Format-ByteSize $downloadedBytes
                    }
                    $status = "$filePercent%｜$sizeText｜实时 {0:N2} MB/s｜平均 {1:N2} MB/s" -f $instantMbps, $averageMbps
                    Write-InstallProgress -Percent $overall -Activity $Activity -Status $status
                    $sampleAt = $now
                    $sampleBytes = $downloadedBytes
                    $lastDisplayAt = $now
                }
            }
            $fileStream.Flush()
            $fileStream.Dispose(); $fileStream = $null
            $networkStream.Dispose(); $networkStream = $null
            $response.Dispose(); $response = $null

            if ($totalBytes -gt 0 -and $downloadedBytes -ne $totalBytes) {
                throw "下载大小不完整：$downloadedBytes / $totalBytes 字节"
            }
            Move-Item -LiteralPath $partialPath -Destination $Destination -Force
            Write-InstallProgress -Percent $ProgressEnd -Activity $Activity `
                -Status ("100%｜{0}｜下载完成" -f (Format-ByteSize $downloadedBytes)) -CompleteLine
            return $Destination
        } catch {
            if ($attempt -ge 3) { throw "下载失败（已重试 3 次，保留断点文件）：$($_.Exception.Message)" }
            Clear-InstallProgressLine
            Write-Warning "下载中断，2 秒后从断点重试（$attempt/3）：$($_.Exception.Message)"
            Start-Sleep -Seconds 2
        } finally {
            if ($fileStream) { $fileStream.Dispose() }
            if ($networkStream) { $networkStream.Dispose() }
            if ($response) { $response.Dispose() }
        }
    }
}

function Invoke-FileDownloadWithProgress {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [string]$Activity,
        [int]$ProgressStart,
        [int]$ProgressEnd,
        [long]$ExpectedSize = -1
    )

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        Write-Warning '未找到 Windows curl.exe，改用 .NET 单连接下载器。'
        return Invoke-DotNetFileDownloadWithProgress @PSBoundParameters
    }

    $partialPath = "$Destination.part"
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    $totalBytes = $ExpectedSize
    if ($totalBytes -le 0) {
        try {
            $head = [Net.HttpWebRequest]::Create($Uri)
            $head.Method = 'HEAD'
            $head.UserAgent = 'DataAnonymization-WSL-Installer/1.0'
            $head.AllowAutoRedirect = $true
            $head.Timeout = 15000
            $head.ReadWriteTimeout = 15000
            $headResponse = $head.GetResponse()
            try { $totalBytes = [long]$headResponse.ContentLength } finally { $headResponse.Dispose() }
        } catch {
            $totalBytes = -1L
        }
    }

    if ((Test-Path -LiteralPath $Destination) -and $totalBytes -gt 0 -and
        (Get-Item -LiteralPath $Destination).Length -eq $totalBytes) {
        Write-InstallProgress -Percent $ProgressEnd -Activity $Activity `
            -Status ("已缓存 {0}，跳过下载" -f (Format-ByteSize $totalBytes)) -CompleteLine
        return $Destination
    }
    if ((Test-Path -LiteralPath $partialPath) -and $totalBytes -gt 0 -and
        (Get-Item -LiteralPath $partialPath).Length -eq $totalBytes) {
        Move-Item -LiteralPath $partialPath -Destination $Destination -Force
        Write-InstallProgress -Percent $ProgressEnd -Activity $Activity `
            -Status ("断点文件已完整，恢复缓存 {0}" -f (Format-ByteSize $totalBytes)) -CompleteLine
        return $Destination
    }

    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $existingBytes = if (Test-Path -LiteralPath $partialPath) {
            [long](Get-Item -LiteralPath $partialPath).Length
        } else {
            0L
        }
        if ($totalBytes -gt 0 -and $existingBytes -gt $totalBytes) {
            Remove-Item -LiteralPath $partialPath -Force
            $existingBytes = 0L
        }

        $arguments = @(
            '--location', '--fail', '--silent', '--show-error',
            '--retry', '3', '--retry-delay', '2', '--connect-timeout', '20',
            '--speed-time', ([string]$WslNoProgressTimeoutSeconds), '--speed-limit', '1024',
            '--user-agent', 'DataAnonymization-WSL-Installer/1.0',
            '--continue-at', '-', '--output', $partialPath, $Uri
        )
        $startInfo = New-Object Diagnostics.ProcessStartInfo
        $startInfo.FileName = $curl.Source
        $startInfo.Arguments = (($arguments | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' ')
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardError = $true
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $startInfo
        $startedAt = [DateTime]::UtcNow
        $sampleAt = $startedAt
        $sampleBytes = $existingBytes
        try {
            if (-not $process.Start()) { throw '无法启动 Windows curl.exe。' }
            while (-not $process.WaitForExit(500)) {
                $downloadedBytes = if (Test-Path -LiteralPath $partialPath) {
                    [long](Get-Item -LiteralPath $partialPath).Length
                } else {
                    0L
                }
                $now = [DateTime]::UtcNow
                $sampleSeconds = [math]::Max(($now - $sampleAt).TotalSeconds, 0.001)
                $instantMbps = [math]::Max(0, (($downloadedBytes - $sampleBytes) / 1MB) / $sampleSeconds)
                $averageSeconds = [math]::Max(($now - $startedAt).TotalSeconds, 0.001)
                $averageMbps = [math]::Max(0, (($downloadedBytes - $existingBytes) / 1MB) / $averageSeconds)
                if ($totalBytes -gt 0) {
                    $filePercent = [math]::Min(100, [math]::Floor($downloadedBytes * 100 / $totalBytes))
                    $overall = $ProgressStart + [math]::Floor(($ProgressEnd - $ProgressStart) * $filePercent / 100)
                    $sizeText = "$(Format-ByteSize $downloadedBytes) / $(Format-ByteSize $totalBytes)"
                } else {
                    $filePercent = 0
                    $overall = $ProgressStart
                    $sizeText = Format-ByteSize $downloadedBytes
                }
                $status = "$filePercent%｜$sizeText｜实时 {0:N2} MB/s｜平均 {1:N2} MB/s" -f $instantMbps, $averageMbps
                Write-InstallProgress -Percent $overall -Activity $Activity -Status $status
                $sampleAt = $now
                $sampleBytes = $downloadedBytes
            }
            $errorText = $process.StandardError.ReadToEnd().Trim()
            $process.WaitForExit()
            $exitCode = $process.ExitCode
        } catch [System.Management.Automation.PipelineStoppedException] {
            Stop-NativeProcessTree $process
            throw
        } finally {
            if ($process) { $process.Dispose() }
        }

        if ($exitCode -eq 0) {
            $downloadedBytes = [long](Get-Item -LiteralPath $partialPath).Length
            if ($totalBytes -gt 0 -and $downloadedBytes -ne $totalBytes) {
                throw "下载大小不完整：$downloadedBytes / $totalBytes 字节"
            }
            Move-Item -LiteralPath $partialPath -Destination $Destination -Force
            Write-InstallProgress -Percent $ProgressEnd -Activity $Activity `
                -Status ("100%｜{0}｜下载完成" -f (Format-ByteSize $downloadedBytes)) -CompleteLine
            return $Destination
        }

        # curl 退出码 33 表示服务端拒绝断点续传；仅此情况清除断点并完整重试一次。
        if ($exitCode -eq 33 -and $existingBytes -gt 0 -and $attempt -lt 2) {
            Clear-InstallProgressLine
            Write-Warning '下载服务器暂不接受该断点，正在从头重试。'
            Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
            continue
        }
        throw "下载失败（curl 退出码 $exitCode，断点文件已保留）：$errorText"
    }
}

function Get-OfficialWslMsiAsset([string]$Architecture) {
    try {
        $release = Invoke-RestMethod -UseBasicParsing `
            -Uri 'https://api.github.com/repos/microsoft/WSL/releases/latest' `
            -Headers @{ 'User-Agent' = 'DataAnonymization-WSL-Installer/1.0'; 'Accept' = 'application/vnd.github+json' } `
            -TimeoutSec 10
        $suffix = if ($Architecture -eq 'Arm64') { '.arm64.msi' } else { '.x64.msi' }
        $asset = @($release.assets | Where-Object { $_.name.EndsWith($suffix) }) | Select-Object -First 1
        if ($asset) { return $asset }
    } catch {
        Write-Warning 'GitHub 官方发布接口暂时不可访问，使用脚本内置的已校验微软稳定版元数据。'
    }

    if ($Architecture -eq 'Arm64') {
        return [pscustomobject]@{
            name = 'wsl.2.7.11.0.arm64.msi'
            size = 257032192
            digest = 'sha256:e90dd92c730dcf0f3ea8786a3e1c513d9085b2df676ed698006e8079b4e8ba71'
            browser_download_url = 'https://github.com/microsoft/WSL/releases/download/2.7.11/wsl.2.7.11.0.arm64.msi'
        }
    }
    return [pscustomobject]@{
        name = 'wsl.2.7.11.0.x64.msi'
        size = 258990080
        digest = 'sha256:a611ddacee689d2fb1fb5319e58af7f3998864d86cdce632eadd8e61614a0f9d'
        browser_download_url = 'https://github.com/microsoft/WSL/releases/download/2.7.11/wsl.2.7.11.0.x64.msi'
    }
}

function Test-WslRestartRequiredResult($Result) {
    if ($null -eq $Result) { return $false }
    if ($Result.PSObject.Properties.Name -contains 'RestartRequired' -and $Result.RestartRequired) {
        return $true
    }
    if ($Result.PSObject.Properties.Name -contains 'ExitCode' -and [int]$Result.ExitCode -eq 3010) {
        return $true
    }
    $outputText = [string]::Join("`n", @($Result.Output))
    return $outputText -match 'WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED'
}

function Install-OfficialWslMsi([string]$Architecture, [int]$ProgressStart, [int]$ProgressEnd) {
    $asset = Get-OfficialWslMsiAsset $Architecture
    $downloadEnd = $ProgressEnd - 2
    $target = Join-Path (Join-Path $runtimeDirectory 'downloads') $asset.name
    $partialTarget = "$target.part"
    $hasCompleteCache = ((Test-Path -LiteralPath $target) -and
        (Get-Item -LiteralPath $target).Length -eq [long]$asset.size) -or
        ((Test-Path -LiteralPath $partialTarget) -and
        (Get-Item -LiteralPath $partialTarget).Length -eq [long]$asset.size)
    $selectedSource = if ($hasCompleteCache) {
        [pscustomobject]@{ Name = '本地完整缓存'; Uri = $asset.browser_download_url; Mbps = 0 }
    } else {
        Select-FastestWslMsiUri $asset.browser_download_url
    }
    Invoke-FileDownloadWithProgress -Uri $selectedSource.Uri -Destination $target `
        -Activity ("下载微软官方 WSL 安装包（{0}）" -f $selectedSource.Name) `
        -ProgressStart $ProgressStart -ProgressEnd $downloadEnd -ExpectedSize ([long]$asset.size) | Out-Null

    if ($asset.digest -and $asset.digest.StartsWith('sha256:')) {
        $expectedHash = $asset.digest.Substring(7).ToLowerInvariant()
        $actualHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            Remove-Item -LiteralPath $target -Force
            throw 'WSL MSI 的 SHA-256 校验失败，已删除文件。'
        }
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $target
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
        $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
        Remove-Item -LiteralPath $target -Force
        throw 'WSL MSI 的微软数字签名无效，已删除文件。'
    }

    $result = Invoke-NativeCommand -FilePath 'msiexec.exe' `
        -ArgumentList @('/i', $target, '/qn', '/norestart') -DisplayOutput `
        -Activity '安装微软签名的 WSL MSI' -ProgressStart $downloadEnd -ProgressEnd $ProgressEnd `
        -CommandTimeoutSeconds 600
    if ($result.ExitCode -notin @(0, 3010)) { throw "WSL MSI 安装失败，退出码：$($result.ExitCode)" }
    return [pscustomobject]@{
        Output = $result.Output
        ExitCode = $result.ExitCode
        TimedOut = $false
        RestartRequired = ($result.ExitCode -eq 3010)
    }
}

function Get-OfficialDistributionAsset([string]$Distribution, [string]$Architecture) {
    try {
        $manifest = Invoke-RestMethod -UseBasicParsing `
            -Uri 'https://raw.githubusercontent.com/microsoft/WSL/master/distributions/DistributionInfo.json' `
            -Headers @{ 'User-Agent' = 'DataAnonymization-WSL-Installer/1.0' } -TimeoutSec 10
        $entry = $null
        foreach ($group in $manifest.ModernDistributions.PSObject.Properties) {
            $entry = @($group.Value | Where-Object { $_.Name -eq $Distribution }) | Select-Object -First 1
            if ($entry) { break }
        }
        if ($entry) {
            $asset = if ($Architecture -eq 'Arm64') { $entry.Arm64Url } else { $entry.Amd64Url }
            if ($asset -and $asset.Url -and $asset.Sha256) { return $asset }
        }
    } catch {
        Write-Warning '微软 WSL 在线发行版清单暂时不可访问，尝试内置的已校验 Ubuntu 24.04 元数据。'
    }

    if ($Distribution -eq 'Ubuntu-24.04') {
        if ($Architecture -eq 'Arm64') {
            return [pscustomobject]@{
                Url = 'https://cdimages.ubuntu.com/releases/24.04.4/release/ubuntu-24.04.4-wsl-arm64.wsl'
                Sha256 = '6b244d89f412a68f51e58f396fab65bed3b5896a25c045a99bef9c78a07df507'
            }
        }
        return [pscustomobject]@{
            Url = 'https://releases.ubuntu.com/24.04.4/ubuntu-24.04.4-wsl-amd64.wsl'
            Sha256 = '9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5'
        }
    }
    throw "微软官方发行版清单不可用，且脚本没有 $Distribution / $Architecture 的内置已校验元数据。"
}

function Install-OfficialDistributionFile(
    [string]$Distribution,
    [string]$Architecture,
    [int]$ProgressStart,
    [int]$ProgressEnd
) {
    $asset = Get-OfficialDistributionAsset $Distribution $Architecture
    $fileName = [IO.Path]::GetFileName(([Uri]$asset.Url).AbsolutePath)
    $downloadEnd = $ProgressEnd - 2
    $target = Join-Path (Join-Path $runtimeDirectory 'downloads') $fileName
    Invoke-FileDownloadWithProgress -Uri $asset.Url -Destination $target `
        -Activity "下载微软清单中的 $Distribution" -ProgressStart $ProgressStart -ProgressEnd $downloadEnd | Out-Null
    $expectedHash = ([string]$asset.Sha256).Trim().ToLowerInvariant()
    if ($expectedHash.StartsWith('0x')) { $expectedHash = $expectedHash.Substring(2) }
    $actualHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        Remove-Item -LiteralPath $target -Force
        throw "$Distribution 安装包的 SHA-256 校验失败，已删除文件。"
    }
    $result = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--install', '--from-file', $target, '--no-launch') -DisplayOutput `
        -Activity "从已校验文件安装 $Distribution" -ProgressStart $downloadEnd -ProgressEnd $ProgressEnd `
        -CommandTimeoutSeconds 600
    if (Test-WslRestartRequiredResult $result) {
        $result | Add-Member -NotePropertyName RestartRequired -NotePropertyValue $true -Force
        return $result
    }
    if ($result.ExitCode -ne 0) { throw "$Distribution 本地安装失败。" }
    return $result
}

function Get-WslChannelOrder {
    if ($WslDownloadChannel -eq 'Web') { return @('Web') }
    if ($WslDownloadChannel -eq 'Store') { return @('Store') }
    Write-Host 'Auto 先尝试官方元数据与实测速下载；失败后再回退 Microsoft Store。' -ForegroundColor Cyan
    return @('Web', 'Store')
}

function Invoke-WslOfficialDownload {
    param(
        [ValidateSet('Update', 'Install')]
        [string]$Operation,
        [string]$Distribution = '',
        [ValidateSet('X64', 'Arm64')]
        [string]$Architecture = 'X64',
        [int]$ProgressStart,
        [int]$ProgressEnd
    )

    $channels = @(Get-WslChannelOrder)
    $lastResult = $null
    for ($index = 0; $index -lt $channels.Count; $index++) {
        $channel = $channels[$index]
        $channelName = if ($channel -eq 'Web') { 'GitHub 官方 Web 通道' } else { 'Microsoft Store 官方通道' }
        if ($channel -eq 'Web') {
            try {
                if ($Operation -eq 'Update') {
                    return Install-OfficialWslMsi -Architecture $Architecture `
                        -ProgressStart $ProgressStart -ProgressEnd $ProgressEnd
                }
                return Install-OfficialDistributionFile -Distribution $Distribution -Architecture $Architecture `
                    -ProgressStart $ProgressStart -ProgressEnd $ProgressEnd
            } catch {
                $lastResult = [pscustomobject]@{
                    Output = @($_.Exception.Message)
                    ExitCode = 1
                    TimedOut = $false
                    TimeoutStatus = ''
                }
                Write-Warning "通过 $channelName 直接下载失败：$($_.Exception.Message)"
                if ($index -ge $channels.Count - 1) { return $lastResult }
                continue
            }
        }
        if ($Operation -eq 'Update') {
            $arguments = @('--update')
            $activity = "通过 $channelName 更新 WSL"
        } else {
            $arguments = @('--install', '--distribution', $Distribution, '--no-launch')
            $activity = "通过 $channelName 安装 $Distribution"
        }
        # Auto 的首选通道无进展时才超时切换；最后一个或用户固定的通道不被脚本强制中断。
        $timeoutForAttempt = if ($channels.Count -gt 1 -and $index -lt $channels.Count - 1) {
            $WslNoProgressTimeoutSeconds
        } else {
            0
        }
        $lastResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList $arguments `
            -DisplayOutput -Activity $activity -ProgressStart $ProgressStart -ProgressEnd $ProgressEnd `
            -NoProgressTimeoutSeconds $timeoutForAttempt
        if (Test-WslRestartRequiredResult $lastResult) { return $lastResult }
        if ($lastResult.ExitCode -eq 0) { return $lastResult }

        if ($index -lt $channels.Count - 1) {
            $nextName = if ($channels[$index + 1] -eq 'Web') { 'GitHub 官方 Web 通道' } else { 'Microsoft Store 官方通道' }
            $reason = if ($lastResult.TimedOut) { "连续 $WslNoProgressTimeoutSeconds 秒没有真实进展" } else { '当前通道返回失败' }
            Write-Warning "$reason，自动切换到 $nextName。"
        }
    }
    return $lastResult
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
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DistroName `"$DistroName`" -ProjectPath `"$ProjectPath`" -WslDownloadChannel $WslDownloadChannel -WslNoProgressTimeoutSeconds $WslNoProgressTimeoutSeconds"
    if ($CheckOnly) { $arguments += ' -CheckOnly' }
    if ($AutoReboot) { $arguments += ' -AutoReboot' }
    if ($ResumeAfterRestart) { $arguments += ' -ResumeAfterRestart' }
    # 保留自动提权后的窗口，让用户能够看到检测结果或错误信息。
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList "-NoExit $arguments"
}

function Set-ResumeAfterRestart {
    $command = "powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -DistroName `"$DistroName`" -ProjectPath `"$ProjectPath`" -WslDownloadChannel $WslDownloadChannel -WslNoProgressTimeoutSeconds $WslNoProgressTimeoutSeconds -ResumeAfterRestart"
    if ($AutoReboot) { $command += ' -AutoReboot' }
    $resumeLocations = @(
        @{ Path = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce'; Scope = '系统级' },
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'; Scope = '当前用户级' }
    )
    foreach ($location in $resumeLocations) {
        try {
            New-ItemProperty -Path $location.Path -Name $ResumeName -Value $command `
                -PropertyType String -Force -ErrorAction Stop | Out-Null
            Write-Host "已登记$($location.Scope)重启续跑项。" -ForegroundColor Green
            return $true
        } catch {
            Write-Warning "$($location.Scope)重启续跑项登记失败：$($_.Exception.Message)"
        }
    }
    Write-Warning '系统策略禁止登记自动续跑；这不会影响已经启用的 WSL2 功能。'
    return $false
}

function Clear-ResumeAfterRestart {
    foreach ($resumePath in @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
    )) {
        try {
            Remove-ItemProperty -Path $resumePath -Name $ResumeName -ErrorAction SilentlyContinue
        } catch {
            Write-Warning "无法清理重启续跑项 $resumePath；可忽略，不影响应用运行。"
        }
    }
}

function Stop-ForRestart([string]$Reason = 'WSL2 系统组件已启用') {
    $resumeRegistered = Set-ResumeAfterRestart
    if ($resumeRegistered) {
        Write-Warning "$Reason，需要重启 Windows。登录后安装脚本会自动继续。"
    } else {
        Write-Warning "$Reason，需要重启 Windows。重启后请在项目目录重新运行本脚本；已完成步骤会自动跳过。"
    }
    if ($AutoReboot) {
        Write-Warning '15 秒后自动重启。若要取消，请立即运行：shutdown /a'
        shutdown.exe /r /t 15 /c '继续安装数据脱敏应用所需的 WSL2'
    } elseif (-not $resumeRegistered) {
        Write-Host '请保存工作并手动重启 Windows；重启后以管理员身份重新运行 .\install-wsl-docker-cn.ps1。' -ForegroundColor Yellow
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
$runTimestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $runtimeDirectory 'install-support-latest.log'
$archiveLogPath = Join-Path $runtimeDirectory ("install-wsl-docker-$runTimestamp.log")
if (Test-Path -LiteralPath $logPath) {
    $previousTail = @(Get-Content -LiteralPath $logPath -Tail 30 -ErrorAction SilentlyContinue)
    if (-not ($previousTail -match '^SUPPORT_LOG_FINALIZED=')) {
        $recoveredLogPath = Join-Path $runtimeDirectory ("install-wsl-docker-recovered-$runTimestamp.log")
        Copy-Item -LiteralPath $logPath -Destination $recoveredLogPath -Force
    }
}
$transcriptStarted = $false
Start-Transcript -Path $logPath -Force | Out-Null
$transcriptStarted = $true
$scriptHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
Write-Host "SUPPORT_LOG_BEGIN=$([DateTime]::Now.ToString('o'))"
Write-Host "支持日志：$logPath" -ForegroundColor Yellow
Write-Host "脚本 SHA-256：$scriptHash"
Write-Host "PowerShell：$($PSVersionTable.PSVersion) / $($PSVersionTable.PSEdition) / $([IntPtr]::Size * 8)-bit"
Write-Host "Windows：$([Environment]::OSVersion.VersionString)"
Write-Host "项目目录：$resolvedProject"
Write-Host "运行参数：发行版=$DistroName；WSL通道=$WslDownloadChannel；仅检测=$CheckOnly；自动重启=$AutoReboot；重启续跑=$ResumeAfterRestart"
Write-Host '安全说明：日志不会主动输出 .env 密码、密钥或令牌；发送前仍应按组织要求作为内部运维资料处理。'

try {
    Write-Step '检测 Windows、硬件与部署资源'
    $probeStepCount = 10
    $os = Invoke-SystemProbeWithTimeout -Name '读取 Windows 版本（WMI）' `
        -StepNumber 1 -StepCount $probeStepCount -ProgressPercent 1 -TimeoutSeconds 15 `
        -ScriptBlock {
            Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 10 -ErrorAction Stop |
                Select-Object -First 1
        }
    $computer = Invoke-SystemProbeWithTimeout -Name '读取内存和虚拟机信息（WMI）' `
        -StepNumber 2 -StepCount $probeStepCount -ProgressPercent 2 -TimeoutSeconds 15 `
        -ScriptBlock {
            Get-CimInstance Win32_ComputerSystem -OperationTimeoutSec 10 -ErrorAction Stop |
                Select-Object -First 1
        }
    $cpu = Invoke-SystemProbeWithTimeout -Name '读取处理器虚拟化信息（WMI）' `
        -StepNumber 3 -StepCount $probeStepCount -ProgressPercent 3 -TimeoutSeconds 15 `
        -ScriptBlock {
            Get-CimInstance Win32_Processor -OperationTimeoutSec 10 -ErrorAction Stop |
                Select-Object -First 1
        }
    if (-not $os) { throw '无法读取 Win32_OperatingSystem 系统信息。请确认 WMI/CIM 服务正在运行。' }
    if (-not $computer) { throw '无法读取 Win32_ComputerSystem 硬件信息。请确认 WMI/CIM 服务正在运行。' }
    if (-not $cpu) { throw '无法读取 Win32_Processor 处理器信息。请确认 WMI/CIM 服务正在运行。' }
    $build = [int]$os.BuildNumber
    $memoryGB = [math]::Round($computer.TotalPhysicalMemory / 1GB, 1)
    $logicalProcessors = if ($computer.NumberOfLogicalProcessors) {
        [int]$computer.NumberOfLogicalProcessors
    } elseif ($cpu.NumberOfLogicalProcessors) {
        [int]$cpu.NumberOfLogicalProcessors
    } else {
        0
    }
    $architecture = Get-WindowsArchitecture $computer $os
    $disk = Invoke-SystemProbeWithTimeout -Name '读取项目磁盘空间（WMI）' `
        -StepNumber 4 -StepCount $probeStepCount -ProgressPercent 4 -TimeoutSeconds 15 `
        -ArgumentList @($resolvedProject) -ScriptBlock {
            param($projectPath)
            $root = [IO.Path]::GetPathRoot([string]$projectPath)
            if ([string]::IsNullOrWhiteSpace($root) -or $root.Length -lt 2) { return }
            $deviceId = $root.Substring(0, 2)
            Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$deviceId'" `
                -OperationTimeoutSec 10 -ErrorAction Stop | Select-Object -First 1
        }
    $diskFreeGB = if ($disk -and $null -ne $disk.FreeSpace) { [math]::Round($disk.FreeSpace / 1GB, 1) } else { 0 }
    $virtualization = [bool]$computer.HypervisorPresent -or [bool]$cpu.VirtualizationFirmwareEnabled
    $portOwner = Invoke-SystemProbeWithTimeout -Name '检查应用端口 5291' `
        -StepNumber 5 -StepCount $probeStepCount -ProgressPercent 5 -TimeoutSeconds 15 `
        -ScriptBlock {
            Get-NetTCPConnection -State Listen -LocalPort 5291 -ErrorAction SilentlyContinue |
                Select-Object -First 1
        }

    $wslFeature = Invoke-SystemProbeWithTimeout -Name '检查 WSL Windows 功能（DISM）' `
        -StepNumber 6 -StepCount $probeStepCount -ProgressPercent 6 -TimeoutSeconds 45 `
        -ScriptBlock {
            Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction Stop
        }
    $vmFeature = Invoke-SystemProbeWithTimeout -Name '检查虚拟机平台功能（DISM）' `
        -StepNumber 7 -StepCount $probeStepCount -ProgressPercent 7 -TimeoutSeconds 45 `
        -ScriptBlock {
            Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction Stop
        }

    $packageMirrorCandidates = @(
        [pscustomobject]@{
            Name = '清华大学 TUNA'; AptMirror = 'https://mirrors.tuna.tsinghua.edu.cn'
            DockerCeMirror = 'https://mirrors.tuna.tsinghua.edu.cn/docker-ce'
            PypiMirror = 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple'
            AptProbe = 'https://mirrors.tuna.tsinghua.edu.cn/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/django/'
        }
        [pscustomobject]@{
            Name = '阿里云'; AptMirror = 'https://mirrors.aliyun.com'
            DockerCeMirror = 'https://mirrors.aliyun.com/docker-ce'
            PypiMirror = 'https://mirrors.aliyun.com/pypi/simple'
            AptProbe = 'https://mirrors.aliyun.com/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirrors.aliyun.com/pypi/simple/django/'
        }
        [pscustomobject]@{
            Name = '中国科学技术大学 USTC'; AptMirror = 'https://mirrors.ustc.edu.cn'
            DockerCeMirror = 'https://mirrors.ustc.edu.cn/docker-ce'
            PypiMirror = 'https://mirrors.ustc.edu.cn/pypi/simple'
            AptProbe = 'https://mirrors.ustc.edu.cn/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirrors.ustc.edu.cn/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirrors.ustc.edu.cn/pypi/simple/django/'
        }
        [pscustomobject]@{
            Name = '华为云'; AptMirror = 'https://mirrors.huaweicloud.com'
            DockerCeMirror = 'https://mirrors.huaweicloud.com/docker-ce'
            PypiMirror = 'https://mirrors.huaweicloud.com/repository/pypi/simple'
            AptProbe = 'https://mirrors.huaweicloud.com/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirrors.huaweicloud.com/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirrors.huaweicloud.com/repository/pypi/simple/django/'
        }
        [pscustomobject]@{
            Name = '腾讯云'; AptMirror = 'https://mirrors.cloud.tencent.com'
            DockerCeMirror = 'https://mirrors.cloud.tencent.com/docker-ce'
            PypiMirror = 'https://mirrors.cloud.tencent.com/pypi/simple'
            AptProbe = 'https://mirrors.cloud.tencent.com/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirrors.cloud.tencent.com/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirrors.cloud.tencent.com/pypi/simple/django/'
        }
        [pscustomobject]@{
            Name = '北京外国语大学 BFSU'; AptMirror = 'https://mirrors.bfsu.edu.cn'
            DockerCeMirror = 'https://mirrors.bfsu.edu.cn/docker-ce'
            PypiMirror = 'https://mirrors.bfsu.edu.cn/pypi/web/simple'
            AptProbe = 'https://mirrors.bfsu.edu.cn/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirrors.bfsu.edu.cn/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirrors.bfsu.edu.cn/pypi/web/simple/django/'
        }
        [pscustomobject]@{
            Name = '南京大学 NJU'; AptMirror = 'https://mirror.nju.edu.cn'
            DockerCeMirror = 'https://mirror.nju.edu.cn/docker-ce'
            PypiMirror = 'https://mirror.nju.edu.cn/pypi/web/simple'
            AptProbe = 'https://mirror.nju.edu.cn/ubuntu/dists/noble/InRelease'
            DockerProbe = 'https://mirror.nju.edu.cn/docker-ce/linux/ubuntu/gpg'
            PypiProbe = 'https://mirror.nju.edu.cn/pypi/web/simple/django/'
        }
    )
    $selectedPackageMirror = $null
    $selectedPackageMirrorLatency = $null
    $availablePackageMirrors = @()
    foreach ($candidate in $packageMirrorCandidates) {
        try {
            $candidateResult = Invoke-SystemProbeWithTimeout -Name "选择软件源：$($candidate.Name)" `
                -StepNumber 8 -StepCount $probeStepCount -ProgressPercent 8 -TimeoutSeconds 12 `
                -ArgumentList @([string]$candidate.AptProbe, [string]$candidate.DockerProbe, `
                    [string]$candidate.PypiProbe) `
                -ScriptBlock {
                    param($aptProbe, $dockerProbe, $pypiProbe)
                    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
                    if (-not $curl) { return -1.0 }
                    $totalSeconds = 0.0
                    foreach ($probeUrl in @($aptProbe, $dockerProbe, $pypiProbe)) {
                        $timingText = & $curl.Source --location --silent --fail --connect-timeout 4 `
                            --max-time 7 --max-filesize 1048576 --range '0-1023' --output NUL `
                            --write-out '%{time_total}' -- $probeUrl 2>$null
                        if ($LASTEXITCODE -ne 0) { return -1.0 }
                        $seconds = 0.0
                        $parsed = [double]::TryParse(
                            ([string]$timingText).Trim(),
                            [Globalization.NumberStyles]::Float,
                            [Globalization.CultureInfo]::InvariantCulture,
                            [ref]$seconds
                        )
                        if (-not $parsed) { return -1.0 }
                        $totalSeconds += $seconds
                    }
                    return $totalSeconds
                }
            $latency = [double]($candidateResult | Select-Object -First 1)
            if ($latency -ge 0) {
                $availablePackageMirrors += [pscustomobject]@{
                    Candidate = $candidate
                    LatencySeconds = $latency
                }
                Write-Host ("  可用：{0}，三项检测共 {1:N2} 秒" -f $candidate.Name, $latency) `
                    -ForegroundColor DarkGreen
                continue
            }
            Write-Warning "$($candidate.Name) 软件源不可访问，自动尝试下一个候选。"
        } catch {
            Write-Warning "$($candidate.Name) 软件源检测失败或超时，自动尝试下一个候选。"
        }
    }
    if ($availablePackageMirrors.Count -gt 0) {
        $fastestPackageMirror = $availablePackageMirrors |
            Sort-Object LatencySeconds | Select-Object -First 1
        $selectedPackageMirror = $fastestPackageMirror.Candidate
        $selectedPackageMirrorLatency = [double]$fastestPackageMirror.LatencySeconds
    }

    $npmCandidates = @(
        [pscustomobject]@{ Name = 'npmmirror'; Registry = 'https://registry.npmmirror.com'; Probe = 'https://registry.npmmirror.com/-/ping'; IsOfficialFallback = $false }
        [pscustomobject]@{ Name = '华为云 npm'; Registry = 'https://mirrors.huaweicloud.com/repository/npm/'; Probe = 'https://mirrors.huaweicloud.com/repository/npm/-/ping'; IsOfficialFallback = $false }
        [pscustomobject]@{ Name = '腾讯云 npm'; Registry = 'https://mirrors.cloud.tencent.com/npm'; Probe = 'https://mirrors.cloud.tencent.com/npm/-/ping'; IsOfficialFallback = $false }
        [pscustomobject]@{ Name = 'npm 官方源'; Registry = 'https://registry.npmjs.org'; Probe = 'https://registry.npmjs.org/-/ping'; IsOfficialFallback = $true }
    )
    $selectedNpmMirror = $null
    $selectedNpmMirrorLatency = $null
    $availableNpmMirrors = @()
    foreach ($candidate in $npmCandidates) {
        try {
            $candidateResult = Invoke-SystemProbeWithTimeout -Name "选择 npm 源：$($candidate.Name)" `
                -StepNumber 9 -StepCount $probeStepCount -ProgressPercent 9 -TimeoutSeconds 9 `
                -ArgumentList @([string]$candidate.Probe) -ScriptBlock {
                    param($probeUrl)
                    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
                    if (-not $curl) { return -1.0 }
                    $timingText = & $curl.Source --location --silent --fail --connect-timeout 4 `
                        --max-time 7 --max-filesize 1048576 --range '0-1023' --output NUL `
                        --write-out '%{time_total}' -- $probeUrl 2>$null
                    if ($LASTEXITCODE -ne 0) { return -1.0 }
                    $seconds = 0.0
                    $parsed = [double]::TryParse(
                        ([string]$timingText).Trim(),
                        [Globalization.NumberStyles]::Float,
                        [Globalization.CultureInfo]::InvariantCulture,
                        [ref]$seconds
                    )
                    if (-not $parsed) { return -1.0 }
                    return $seconds
                }
            $latency = [double]($candidateResult | Select-Object -First 1)
            if ($latency -ge 0) {
                $availableNpmMirrors += [pscustomobject]@{
                    Candidate = $candidate
                    LatencySeconds = $latency
                }
                Write-Host ("  可用：{0}，检测用时 {1:N2} 秒" -f $candidate.Name, $latency) `
                    -ForegroundColor DarkGreen
                continue
            }
            Write-Warning "$($candidate.Name) 不可访问，自动尝试下一个候选。"
        } catch {
            Write-Warning "$($candidate.Name) 检测失败或超时，自动尝试下一个候选。"
        }
    }
    if ($availableNpmMirrors.Count -gt 0) {
        $preferredNpmMirrors = @($availableNpmMirrors | Where-Object {
                -not $_.Candidate.IsOfficialFallback
            })
        $npmSelectionPool = if ($preferredNpmMirrors.Count -gt 0) {
            $preferredNpmMirrors
        } else {
            $availableNpmMirrors
        }
        $fastestNpmMirror = $npmSelectionPool |
            Sort-Object LatencySeconds | Select-Object -First 1
        $selectedNpmMirror = $fastestNpmMirror.Candidate
        $selectedNpmMirrorLatency = [double]$fastestNpmMirror.LatencySeconds
    }

    $containerMirrorCandidates = @(
        [pscustomobject]@{
            Name = 'DaoCloud'; Host = 'm.daocloud.io'
            ImagePrefix = 'm.daocloud.io/docker.io/library/'
            RegistryMirror = 'https://docker.m.daocloud.io'; IsOfficialFallback = $false
        }
        [pscustomobject]@{
            Name = 'Docker Hub 官方地址'; Host = 'registry-1.docker.io'
            ImagePrefix = ''; RegistryMirror = ''; IsOfficialFallback = $true
        }
    )
    $selectedContainerMirror = $null
    foreach ($candidate in $containerMirrorCandidates) {
        try {
            $candidateResult = Invoke-SystemProbeWithTimeout -Name "选择容器镜像源：$($candidate.Name)" `
                -StepNumber 10 -StepCount $probeStepCount -ProgressPercent 10 -TimeoutSeconds 10 `
                -ArgumentList @([string]$candidate.Host) -ScriptBlock {
                    param($hostName)
                    $ProgressPreference = 'SilentlyContinue'
                    return Test-NetConnection -ComputerName $hostName -Port 443 `
                        -InformationLevel Quiet -WarningAction SilentlyContinue
                }
            if ([bool]($candidateResult | Select-Object -First 1)) {
                $selectedContainerMirror = $candidate
                break
            }
            Write-Warning "$($candidate.Name) 不可访问，自动尝试下一个候选。"
        } catch {
            Write-Warning "$($candidate.Name) 检测超时，自动尝试下一个候选。"
        }
    }

    $selectedMirrorConfig = if ($selectedPackageMirror -and $selectedNpmMirror -and $selectedContainerMirror) {
        [ordered]@{
            AptMirror = [string]$selectedPackageMirror.AptMirror
            DockerCeMirror = [string]$selectedPackageMirror.DockerCeMirror
            PypiMirror = [string]$selectedPackageMirror.PypiMirror
            NpmMirror = [string]$selectedNpmMirror.Registry
            DockerHubPrefix = [string]$selectedContainerMirror.ImagePrefix
            DockerRegistryMirror = [string]$selectedContainerMirror.RegistryMirror
        }
    } else { $null }

    $results = @(
        [pscustomobject]@{ Item = 'Windows'; Result = $os.Caption; Required = 'Windows 10 2004 / Build 19041 或 Windows 11' }
        [pscustomobject]@{ Item = '系统版本'; Result = "Build $build"; Required = "Build >= $MinimumBuild" }
        [pscustomobject]@{ Item = '体系结构'; Result = $architecture; Required = 'X64 或 Arm64' }
        [pscustomobject]@{ Item = 'CPU 虚拟化'; Result = if ($virtualization) { '已启用' } else { '未检测到' }; Required = 'BIOS/UEFI 中启用' }
        [pscustomobject]@{ Item = 'CPU 逻辑核心'; Result = if ($logicalProcessors) { "$logicalProcessors 核" } else { '无法识别' }; Required = ">= $MinimumLogicalProcessors 核，建议 >= $RecommendedLogicalProcessors 核" }
        [pscustomobject]@{ Item = '物理内存'; Result = "$memoryGB GB"; Required = ">= $MinimumMemoryGB GB，常驻模式建议 >= $RecommendedMemoryGB GB" }
        [pscustomobject]@{ Item = '项目盘可用空间'; Result = "$diskFreeGB GB"; Required = ">= $MinimumDiskGB GB，建议 >= $RecommendedDiskGB GB" }
        [pscustomobject]@{ Item = 'WSL 组件'; Result = $wslFeature.State; Required = 'Enabled（脚本可自动启用）' }
        [pscustomobject]@{ Item = '虚拟机平台'; Result = $vmFeature.State; Required = 'Enabled（脚本可自动启用）' }
        [pscustomobject]@{ Item = '应用端口 5291'; Result = if ($portOwner) { "已占用，PID $($portOwner.OwningProcess)" } else { '可用' }; Required = '部署时需可用' }
        [pscustomobject]@{
            Item = '软件与容器镜像'
            Result = if ($selectedMirrorConfig) { "$($selectedPackageMirror.Name) / $($selectedNpmMirror.Name) / $($selectedContainerMirror.Name)" } else { '没有完整的可用组合' }
            Required = '每类至少一个候选可访问'
        }
    )
    $results | Format-Table -AutoSize
    Write-Host ''
    Write-Host 'PP-StructureV3 精简模式 + UIE-base 配置说明：' -ForegroundColor Cyan
    Write-Host "  最低配置：$MinimumLogicalProcessors 个逻辑核心、$MinimumMemoryGB GB 内存、$MinimumDiskGB GB 可用空间（UIE 必须选择临时调用）。"
    Write-Host "  建议配置：$RecommendedLogicalProcessors 个及以上逻辑核心、$RecommendedMemoryGB GB 内存、$RecommendedDiskGB GB 可用 SSD 空间。"

    $blocking = New-Object System.Collections.Generic.List[string]
    if ($build -lt $MinimumBuild) { $blocking.Add("Windows Build $build 低于 $MinimumBuild，请先运行 Windows Update。") }
    if ($architecture -notin @('X64', 'Arm64')) { $blocking.Add("不支持的体系结构：$architecture。") }
    if (-not $virtualization) { $blocking.Add('未检测到硬件虚拟化，请在 BIOS/UEFI 中启用 Intel VT-x 或 AMD-V。') }
    if (-not $logicalProcessors) {
        $blocking.Add('无法读取 CPU 逻辑核心数，请检查 WMI/CIM 服务状态。')
    } elseif ($logicalProcessors -lt $MinimumLogicalProcessors) {
        $blocking.Add("CPU 逻辑核心不足 $MinimumLogicalProcessors 个。")
    }
    if ($memoryGB -lt $MinimumMemoryGB) { $blocking.Add("内存不足 $MinimumMemoryGB GB。") }
    if ($diskFreeGB -lt $MinimumDiskGB) { $blocking.Add("项目所在磁盘可用空间不足 $MinimumDiskGB GB。") }
    if (-not (Test-Path (Join-Path $resolvedProject 'docker-compose.yml'))) { $blocking.Add('项目目录缺少 docker-compose.yml。') }
    if (-not $selectedPackageMirror) {
        $blocking.Add("以下软件源均不可访问：$(($packageMirrorCandidates.Name) -join '、')。")
    }
    if (-not $selectedNpmMirror) {
        $blocking.Add("以下 npm 源均不可访问：$(($npmCandidates.Name) -join '、')。")
    }
    if (-not $selectedContainerMirror) { $blocking.Add('DaoCloud 和 Docker Hub 官方地址均不可访问。') }

    if ($logicalProcessors -and $logicalProcessors -lt $RecommendedLogicalProcessors -and $logicalProcessors -ge $MinimumLogicalProcessors) {
        Write-Warning "CPU 低于建议值 $RecommendedLogicalProcessors 个逻辑核心，精简 OCR 与 UIE-base 推理可能较慢。"
    }
    if ($memoryGB -lt $RecommendedMemoryGB -and $memoryGB -ge $MinimumMemoryGB) {
        Write-Warning "内存低于常驻模式建议值 $RecommendedMemoryGB GB，请优先选择【临时调用】。"
    }
    if ($diskFreeGB -lt $RecommendedDiskGB -and $diskFreeGB -ge $MinimumDiskGB) {
        Write-Warning "磁盘空间低于建议值 $RecommendedDiskGB GB，请定期清理不用的 Docker 镜像。"
    }
    if ($portOwner) {
        Write-Warning "端口 5291 当前由 PID $($portOwner.OwningProcess) 监听；若不是本项目，部署会失败。"
    }
    if ($selectedPackageMirror) {
        Write-Host ("已选择最快软件源：{0}（检测 {1:N2} 秒）" -f `
                $selectedPackageMirror.Name, $selectedPackageMirrorLatency) -ForegroundColor Green
    }
    if ($selectedNpmMirror) {
        Write-Host ("已选择最快 npm 源：{0}（检测 {1:N2} 秒）" -f `
                $selectedNpmMirror.Name, $selectedNpmMirrorLatency) -ForegroundColor Green
        if ($selectedNpmMirror.IsOfficialFallback) { Write-Warning '国内 npm 镜像不可用，本次将使用 npm 官方源。' }
    }
    if ($selectedContainerMirror) {
        Write-Host "已选择容器镜像源：$($selectedContainerMirror.Name)" -ForegroundColor Green
        if ($selectedContainerMirror.IsOfficialFallback) { Write-Warning 'DaoCloud 不可用，本次将直接使用 Docker Hub 官方地址。' }
    }
    if ($blocking.Count -gt 0) {
        throw ("系统不符合安装要求：`n- " + ($blocking -join "`n- "))
    }
    Write-InstallProgress -Percent 10 -Activity '系统与部署资源检测' -Status '完成' -CompleteLine
    if ($CheckOnly) {
        Clear-InstallProgressLine
        Write-Host "`n系统满足最低安装要求；未修改任何 WSL 或 Docker 配置。" -ForegroundColor Green
        return
    }
    if (-not $ResumeAfterRestart -and -not (Confirm-Installation)) {
        Write-Host "`n已取消安装；未修改任何 WSL 或 Docker 配置。" -ForegroundColor Yellow
        return
    }

    Write-Step '检测主机现有的 WSL、Ubuntu 与 Docker'
    $wslRuntimeVersion = Get-WslRuntimeVersion -ShowDetectionProgress
    $installedDistros = Get-InstalledWslDistros -ShowDetectionProgress
    $distroInstalled = $DistroName -in $installedDistros
    $distroGeneration = if ($distroInstalled) {
        Get-WslDistroGeneration $DistroName -ShowDetectionProgress
    } else {
        Write-InstallProgress -Percent 18 -Activity "检测 $DistroName 的 WSL 版本" `
            -Status '发行版未安装，已跳过' -CompleteLine
        $null
    }
    $wslDocker = if ($distroInstalled) {
        Get-WslDockerVersions $DistroName $distroGeneration -ShowDetectionProgress
    } else {
        Write-InstallProgress -Percent 20 -Activity '检测 Docker 与 Compose 版本' `
            -Status '发行版未安装，已跳过' -CompleteLine
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
    Write-InstallProgress -Percent 20 -Activity '现有 WSL、Ubuntu 与 Docker 检测' -Status '完成' -CompleteLine

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
    Write-InstallProgress -Percent 25 -Activity 'WSL2 Windows 功能' -Status '已就绪' -CompleteLine

    Write-Step "安装并初始化 $DistroName（WSL2）"
    if (-not $wslRuntimeVersion -or $wslRuntimeVersion -lt $MinimumWslVersion) {
        Write-Host "WSL 未安装或低于 $MinimumWslVersion，开始安装/更新。" -ForegroundColor Yellow
        $wslResult = Invoke-WslOfficialDownload -Operation Update -Architecture $architecture `
            -ProgressStart 25 -ProgressEnd 40
        if (Test-WslRestartRequiredResult $wslResult) {
            Stop-ForRestart -Reason 'WSL 运行时已安装并等待系统完成配置'
            return
        }
        if ($wslResult.ExitCode -ne 0) {
            throw 'WSL 运行时安装/更新失败。Auto 已尝试可用的微软官方通道；请检查 Microsoft Store/GitHub 网络后重试。'
        }
        $wslRuntimeVersion = Get-WslRuntimeVersion -ShowDetectionProgress `
            -ProgressStart 40 -ProgressEnd 40 -Activity '验证已安装的 WSL 运行时版本'
        if (-not $wslRuntimeVersion -or $wslRuntimeVersion -lt $MinimumWslVersion) {
            throw "WSL 更新后仍未达到 systemd 所需的最低版本 $MinimumWslVersion。"
        }
    } else {
        Write-Host "WSL $wslRuntimeVersion 已满足要求，跳过重复安装/更新。" -ForegroundColor Green
        Write-InstallProgress -Percent 40 -Activity 'WSL 运行时' -Status '版本满足要求，已跳过' -CompleteLine
    }
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--set-default-version', '2') `
        -DisplayOutput -Activity '设置默认 WSL 版本为 2' -ProgressStart 40 -ProgressEnd 42
    if (Test-WslRestartRequiredResult $wslResult) {
        Stop-ForRestart -Reason 'WSL2 组件仍在等待系统重启'
        return
    }
    if ($wslResult.ExitCode -ne 0) { throw '无法把 WSL 默认版本设为 2。请先完成 Windows Update。' }

    if ($DistroName -notin $installedDistros) {
        $wslResult = Invoke-WslOfficialDownload -Operation Install -Distribution $DistroName `
            -Architecture $architecture `
            -ProgressStart 42 -ProgressEnd 57
        if (Test-WslRestartRequiredResult $wslResult) {
            Stop-ForRestart -Reason "$DistroName 安装所需的 WSL2 组件仍在等待系统重启"
            return
        }
        if ($wslResult.ExitCode -ne 0) { throw "$DistroName 安装失败。Auto 已尝试可用的微软官方通道，请检查网络后重试。" }
        $installedDistros = Get-InstalledWslDistros -ShowDetectionProgress `
            -ProgressStart 57 -ProgressEnd 57 -Activity "验证已安装的 $DistroName"
        if ($DistroName -notin $installedDistros) { throw "$DistroName 安装后未出现在 WSL 发行版列表中。" }
    } else {
        Write-Host "$DistroName 已安装，跳过重复安装。" -ForegroundColor Green
        Write-InstallProgress -Percent 57 -Activity $DistroName -Status '已安装，已跳过' -CompleteLine
    }

    $distroGeneration = Get-WslDistroGeneration $DistroName
    if ($distroGeneration -ne 2) {
        $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--set-version', $DistroName, '2') `
            -DisplayOutput -Activity "将 $DistroName 转换为 WSL2" -ProgressStart 57 -ProgressEnd 62
        if ($wslResult.ExitCode -ne 0) { throw "无法把 $DistroName 转换为 WSL2。" }
    } else {
        Write-Host "$DistroName 已是 WSL2，跳过版本转换。" -ForegroundColor Green
        Write-InstallProgress -Percent 62 -Activity 'WSL2 发行版版本' -Status '已满足要求' -CompleteLine
    }
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'bash', '-lc', 'true') `
        -DisplayOutput -Activity "初始化 $DistroName" -ProgressStart 62 -ProgressEnd 65
    if ($wslResult.ExitCode -ne 0) { throw "$DistroName 初始化失败。" }

    $linuxProject = ConvertTo-WslPath -Distribution $DistroName -WindowsPath $resolvedProject
    $bootstrapPath = Join-Path $runtimeDirectory 'wsl-bootstrap.sh'
    Write-WslBootstrap $bootstrapPath $selectedMirrorConfig
    $linuxInstaller = ConvertTo-WslPath -Distribution $DistroName -WindowsPath $bootstrapPath
    $deployProgressPath = Join-Path $runtimeDirectory 'wsl-deploy-progress.txt'
    $linuxDeployProgressPath = ConvertTo-WslPath -Distribution $DistroName -WindowsPath $runtimeDirectory
    $linuxDeployProgressPath = "$linuxDeployProgressPath/wsl-deploy-progress.txt"

    Write-Step '在 WSL 中配置国内镜像并安装 Docker Engine'
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'bash', $linuxInstaller, 'prepare', $linuxProject) `
        -DisplayOutput -Activity '配置大陆镜像并安装 Docker' -ProgressStart 65 -ProgressEnd 78
    if ($wslResult.ExitCode -ne 0) { throw 'WSL 内的 Docker 安装或镜像配置失败。' }

    Write-Step '重启 WSL，使 systemd 与 Docker 服务生效'
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' -ArgumentList @('--shutdown') `
        -DisplayOutput -Activity '关闭 WSL 以应用 systemd 配置' -ProgressStart 78 -ProgressEnd 80
    if ($wslResult.ExitCode -ne 0) { throw 'WSL 重启失败。' }
    Start-Sleep -Seconds 3

    $hostAddresses = @('localhost', '127.0.0.1')
    $hostAddresses += @(Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp, Manual -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } |
        Select-Object -ExpandProperty IPAddress)
    $allowedHosts = ($hostAddresses | Select-Object -Unique) -join ','

    Write-Step '生成安全配置、构建容器并启动应用'
    $wslResult = Invoke-NativeCommand -FilePath 'wsl.exe' `
        -ArgumentList @('--distribution', $DistroName, '--user', 'root', '--', 'env', "APP_ALLOWED_HOSTS=$allowedHosts", "DA_PROGRESS_FILE=$linuxDeployProgressPath", 'bash', $linuxInstaller, 'deploy', $linuxProject) `
        -DisplayOutput -Activity '构建容器并部署应用' -ProgressStart 80 -ProgressEnd 95 `
        -ProgressStatePath $deployProgressPath
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

    Write-Step '配置 WSL 常驻与 Windows 登录自动启动方式'
    $keepAliveResult = Register-WslKeepAliveTask -Distribution $DistroName -LinuxProjectPath $linuxProject
    $keepAliveStatus = if ($keepAliveResult.Mode -eq 'ScheduledTask') {
        "登录计划任务已启动：$KeepAliveTaskName"
    } else {
        "系统策略拒绝计划任务，已启动当前会话后台保活（PID $($keepAliveResult.ProcessId)）"
    }
    Write-InstallProgress -Percent 95 -Activity 'WSL 常驻方式' -Status $keepAliveStatus -CompleteLine

    Write-Step '从 Windows 持续检查应用端口与健康状态'
    $stabilityResult = Wait-WindowsApplicationStable
    if (-not $stabilityResult.Healthy) {
        throw "WSL 保活方式为 [$($keepAliveResult.Detail)]，但 Windows 无法持续访问 http://127.0.0.1:5291/api/health/ 或 http://localhost:5291/api/health/。"
    }
    if ($keepAliveResult.Mode -eq 'ScheduledTask') {
        $keepAliveTask = Get-ScheduledTask -TaskName $KeepAliveTaskName -ErrorAction SilentlyContinue
        if (-not $keepAliveTask -or $keepAliveTask.State -ne 'Running') {
            $taskState = if ($keepAliveTask) { [string]$keepAliveTask.State } else { '不存在' }
            throw "网站健康检查通过，但 WSL 常驻任务状态为 $taskState，不能保证安装窗口关闭后继续运行。"
        }
    } else {
        $keepAliveProcess = Get-Process -Id $keepAliveResult.ProcessId -ErrorAction SilentlyContinue
        if (-not $keepAliveProcess) {
            throw '网站健康检查通过，但当前会话后台保活进程已经退出。'
        }
    }
    Write-InstallProgress -Percent 100 -Activity '应用健康检查' -Status '安装部署完成' -CompleteLine
    Clear-InstallProgressLine

    Clear-ResumeAfterRestart
    Remove-Item -LiteralPath $bootstrapPath -Force -ErrorAction SilentlyContinue
    Write-Host "`n安装和部署全部完成：http://127.0.0.1:5291" -ForegroundColor Green
    Write-Host "备用地址：http://localhost:5291"
    if ($keepAliveResult.Mode -eq 'ScheduledTask') {
        Write-Host "WSL 常驻任务：$KeepAliveTaskName（Windows 登录后自动恢复应用）"
    } else {
        Write-Host "WSL 保活：当前登录会话后台进程 PID $($keepAliveResult.ProcessId)" -ForegroundColor Yellow
        Write-Warning '系统策略拒绝创建登录计划任务；本次登录期间应用可持续运行。Windows 重启或注销后，请重新运行本脚本恢复应用，或由管理员放行计划任务创建权限。'
    }
    Write-Host "支持日志（可直接发送给维护人员）：$logPath"
    Write-Host "本次日志归档：$archiveLogPath"
}
catch {
    Clear-InstallProgressLine
    Write-Host "`n安装失败：$($_.Exception.Message)" -ForegroundColor Red
    if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
        Write-Host "错误位置：$($_.InvocationInfo.PositionMessage)" -ForegroundColor Red
    }
    if ($_.ScriptStackTrace) {
        Write-Host "调用栈：$($_.ScriptStackTrace)" -ForegroundColor DarkRed
    }
    Write-Host "支持日志（请直接把此文件发给维护人员）：$logPath" -ForegroundColor Yellow
    Write-Host "本次日志归档：$archiveLogPath" -ForegroundColor Yellow
    # 抛回调用者而不是退出整个 PowerShell 主机，避免窗口直接关闭。
    throw
}
finally {
    Clear-InstallProgressLine
    if (Get-Variable -Name bootstrapPath -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $bootstrapPath -Force -ErrorAction SilentlyContinue
    }
    if ($transcriptStarted) {
        Write-Host "SUPPORT_LOG_FINALIZED=$([DateTime]::Now.ToString('o'))"
        try { Stop-Transcript | Out-Null } catch { }
        try { Copy-Item -LiteralPath $logPath -Destination $archiveLogPath -Force } catch { }
    }
}
