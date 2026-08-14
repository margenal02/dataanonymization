# Linux 主机 Docker 部署说明

本文用于将数据脱敏应用直接部署到 Linux 主机，不使用 WSL。Windows 用户请使用仓库根目录唯一的一键脚本 `install-wsl-docker-cn.ps1`；Linux 主机不需要、也不能运行该 PowerShell 脚本。

## 1. 支持范围

推荐使用 64 位 Ubuntu Server 22.04 LTS 或 24.04 LTS。Docker 官方目前也支持更新的 Ubuntu 版本，但生产部署优先选择 LTS。安装与运维采用以下兼容范围：

| 项目 | 要求 |
|---|---|
| CPU | x86_64/amd64 或 arm64；最低 4 个逻辑核心，建议 6 个及以上 |
| 内存 | 最低 8 GB（UIE 临时调用），建议 16 GB 以上（模型常驻） |
| 磁盘 | 至少 30 GB 可用，建议 40 GB 以上 SSD 空间 |
| Docker Engine | `>= 24.0` 且 `< 30.0`（24.x–29.x） |
| Docker Compose 插件 | `>= 2.20` 且 `< 6.0`（v2.20–v5.x） |
| 网络端口 | TCP 5291，仅向可信内网开放 |

以下命令以 Ubuntu 22.04/24.04 和中国大陆网络为例。请使用具备 `sudo` 权限的普通运维账号，不要长期直接登录 root。

UIE-micro 运行在后端容器内，不会另装一套 Docker。“临时调用”在每个任务期间启动模型进程并在结束后释放约 0.9～1.5 GB 模型内存；“模型常驻”复用同一个进程，适合连续批量处理。两种模式使用同一个已经封装到镜像内的本地模型。

## 2. 检查已有 Docker

先查看现有版本：

```bash
docker --version
docker compose version
```

如果 Engine 与 Compose 均位于上表范围，直接跳到“准备项目与安全配置”，不需要重复安装。Engine 低于 24 或 Compose 低于 2.20 时再执行下一节。若版本达到或超过上限，不建议自动降级；应先在测试主机验证项目，或安装项目已验证的版本。

## 3. 安装 Docker Engine 与 Compose

移除可能冲突的发行版软件包：

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg" 2>/dev/null || true
done
```

使用清华大学 TUNA Docker CE 镜像仓库：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu/gpg \
  | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
printf '%s\n' \
  'Types: deb' \
  'URIs: https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu' \
  "Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}" \
  'Components: stable' \
  "Architectures: $(dpkg --print-architecture)" \
  'Signed-By: /etc/apt/keyrings/docker.gpg' \
  | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null

sudo apt-get update

# 列出仓库版本，选择同时落在项目支持范围内的版本；下列值仅为格式示例。
apt-cache madison docker-ce
apt-cache madison docker-compose-plugin
DOCKER_VERSION='5:29.6.2-1~ubuntu.24.04~noble'  # 按上一步实际输出修改
COMPOSE_VERSION='5.1.4-1~ubuntu.24.04~noble'   # 按上一步实际输出修改
sudo apt-get install -y \
  "docker-ce=$DOCKER_VERSION" "docker-ce-cli=$DOCKER_VERSION" \
  containerd.io docker-buildx-plugin "docker-compose-plugin=$COMPOSE_VERSION"
sudo systemctl enable --now docker containerd
```

软件包完整版本会随 Ubuntu 版本和镜像仓库更新而变化，不能原样照抄示例值。Engine 请选择 24.x–29.x，Compose 请选择 v2.20–v5.x；如果仓库已经不再提供兼容版本，先不要安装更高主版本，应在测试环境验证后再调整项目兼容范围。

配置 Docker Hub 中国大陆镜像加速和日志轮转。若主机已有 `/etc/docker/daemon.json`，请先备份并将下列字段合并进去，不要直接覆盖其他生产配置：

```json
{
  "registry-mirrors": ["https://docker.m.daocloud.io"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

保存后重启并复查：

```bash
sudo systemctl restart docker
docker --version
docker compose version
sudo docker info
```

## 4. 准备项目与安全配置

将完整仓库复制或克隆到 Linux 本地磁盘，例如 `/opt/dataanonymization`。中国大陆网络无法连接 GitHub 时，可在可联网电脑下载仓库后通过单位批准的介质离线传入，不要关闭 TLS 校验。

```bash
sudo mkdir -p /opt/dataanonymization
sudo chown "$(id -u):$(id -g)" /opt/dataanonymization
cd /opt/dataanonymization
# 将项目文件放入此目录；若网络允许，也可在父目录执行 git clone。
test -f docker-compose.yml
```

从示例创建 `.env`，生成独立随机密钥，不要把 `.env` 提交到 Git：

```bash
cp .env.example .env
sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$(openssl rand -hex 48)|" .env
sed -i "s|^MAPPING_ENCRYPTION_KEY=.*|MAPPING_ENCRYPTION_KEY=$(openssl rand -hex 48)|" .env
sed -i "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=$(openssl rand -hex 32)|" .env
sed -i "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$(openssl rand -hex 32)|" .env
chmod 600 .env
```

编辑 `.env` 并确认：

- `DJANGO_DEBUG=0`；
- `ALLOWED_HOSTS` 包含服务器 IP 或内部域名；
- 镜像地址适用于当前网络；
- 所有 `please-change-`、`local-dev-` 示例值均已替换；
- `MAPPING_ENCRYPTION_KEY` 已离线加密备份。该密钥丢失后，历史任务无法反匿名。

## 5. 启动与验证

```bash
cd /opt/dataanonymization
sudo docker compose pull db nginx
sudo docker compose up -d --build --remove-orphans
sudo docker compose ps
curl -fsS http://127.0.0.1:5291/api/health/
```

首次构建后端镜像会安装 PaddlePaddle/PaddleNLP 并预取 UIE-micro，耗时和镜像体积会明显增加。构建成功后任务推理不需要访问外部模型服务。若生产网络禁止访问公共源，应先在联网构建机完成镜像构建与漏洞扫描，再通过单位批准的 Harbor/制品库离线导入目标主机。

健康接口返回成功后，在可信内网浏览器访问 `http://服务器IP:5291`。

## 6. 防火墙与安全边界

本应用按需求不提供登录，因此绝不能把 5291 直接开放到互联网。使用主机防火墙仅允许可信办公网段访问；下面以 `192.168.10.0/24` 为例，必须换成实际网段：

```bash
sudo ufw allow from 192.168.10.0/24 to any port 5291 proto tcp
sudo ufw status
```

Docker 发布端口可能绕过部分 UFW 规则。生产环境还应在上游防火墙限制来源，或将规则加入 `DOCKER-USER` 链；跨网访问应由组织网关提供 HTTPS、身份认证和审计。

## 7. 日常运维

```bash
cd /opt/dataanonymization
sudo docker compose ps
sudo docker compose logs -f --tail=200
sudo docker compose down              # 停止但保留数据卷
sudo docker compose up -d             # 重新启动
sudo docker compose up -d --build     # 更新代码后重建
```

定期备份 MySQL 数据卷、`media_data` 文件卷和 `.env` 中的映射加密密钥。不要执行 `docker compose down -v`，除非已经确认要永久删除数据库与保存文件。

## 8. 官方参考

- [Docker：在 Ubuntu 安装 Docker Engine](https://docs.docker.com/engine/install/ubuntu/)
- [Docker：安装 Compose 插件](https://docs.docker.com/compose/install/linux/)
- [Docker：数据包过滤与防火墙](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [清华大学 TUNA：Docker CE 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/docker-ce/)
