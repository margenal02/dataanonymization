# Windows + WSL2 + Docker 中国大陆一键安装说明

本项目只需一个 Windows PowerShell 脚本 `install-wsl-docker-cn.ps1`，可按顺序完成系统检测、WSL2/Ubuntu 安装、Docker Engine 与 Compose 安装、国内镜像配置、安全密钥生成、容器部署和健康检查。脚本执行时会在已忽略的 `.runtime` 目录临时展开 WSL 命令，成功后自动删除，不需要附带第二个安装脚本。

## 系统要求

| 项目 | 最低要求 | 建议配置 |
|---|---:|---:|
| Windows | Windows 10 2004（Build 19041）或 Windows 11 | 安装最新累积更新 |
| 体系结构 | 64 位 X64 或 Arm64 | X64 |
| CPU | BIOS/UEFI 已启用 Intel VT-x 或 AMD-V | 4 核及以上 |
| 内存 | 4 GB | 8 GB 及以上 |
| 项目盘剩余空间 | 20 GB | 30 GB 及以上 |
| 网络 | 能访问 Microsoft WSL 服务及所配置国内镜像 | 稳定宽带 |
| 端口 | TCP 5291 未被其他程序占用 | 仅向可信内网开放 |

Windows 10 家庭版、专业版、企业版和教育版只要达到上述版本并支持 WSL2，均可使用。WSL 本身是 Windows 签名系统组件，仍从 Microsoft 官方服务安装；Ubuntu APT、Docker CE、PyPI、npm 和应用基础容器使用中国大陆镜像。

脚本默认部署 Ubuntu 24.04、Docker Engine 24 或更高版本、Docker Compose v2.20 或更高版本、Python 3.13、Django 5.2、MySQL 8.4、Node.js 22 和 Nginx 1.27。Docker 与 Compose 从镜像仓库安装当前稳定版；已有版本低于兼容线时会自动升级。

## 使用方法

1. 将完整项目目录复制或克隆到 Windows 本地磁盘。
2. 右键点击“Windows PowerShell”，选择“以管理员身份运行”，进入项目目录。
3. 如果希望先做只读检测，执行：

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install-wsl-docker-cn.ps1 -CheckOnly
   ```

4. 检测通过后可执行：

   ```powershell
   .\install-wsl-docker-cn.ps1
   ```

脚本需要管理员权限；如果从普通 PowerShell 启动，会自动打开管理员窗口。该窗口在检测或安装结束后保持打开，便于查看结果和错误日志，可确认完成后手动关闭。

首次启用 WSL2 时需要重启 Windows。脚本会写入一次性的 `RunOnce` 续跑项；手动重启并登录原管理员账号后，安装会自动继续。全部完成后续跑项会自动清除。

如果希望脚本在启用 WSL2 后自动重启：

```powershell
.\install-wsl-docker-cn.ps1 -AutoReboot
```

自动重启有 15 秒缓冲时间，可运行 `shutdown /a` 取消。

## 自动配置的镜像

| 依赖 | 默认中国大陆来源 |
|---|---|
| Ubuntu APT | 清华大学 TUNA |
| Docker CE 软件包 | 清华大学 TUNA |
| Python / Django 包 | 清华大学 TUNA PyPI |
| npm 包 | npmmirror |
| Python、MySQL、Node、Nginx 容器 | DaoCloud 公共镜像代理 |
| Docker Hub 加速 | DaoCloud |

国内公共镜像属于外部依赖，服务地址可能调整。生产环境建议将所需镜像同步到组织自有的 Harbor/制品库，并将 `.env` 中的四个镜像地址改为内部地址。

## 安全配置

首次部署且项目中不存在 `.env` 时，脚本使用 OpenSSL 随机生成：

- Django 应用密钥；
- 匿名映射加密密钥；
- MySQL root 密码；
- MySQL 应用账号密码。

脚本会同时设置 WSL 文件权限和 Windows NTFS ACL，仅保留当前管理员、SYSTEM 和本机管理员组权限。请离线备份 `MAPPING_ENCRYPTION_KEY`；该密钥丢失后，已保存任务无法反匿名。脚本不会覆盖已有 `.env`，如果其中仍含示例弱密钥则会拒绝部署。

本应用按需求无需登录，因此请勿把 `5291` 直接暴露到互联网。建议只允许可信办公内网访问，并在正式环境通过组织网关增加 HTTPS、身份认证和访问审计。

## 安装后操作

访问地址：<http://localhost:5291>

进入 WSL 后查看状态和日志：

```powershell
wsl -d Ubuntu-24.04 -u root
```

```bash
cd /mnt/d/code/dataanonymization  # 按实际项目路径修改
docker compose ps
docker compose logs -f
docker compose down               # 停止服务，保留数据卷
docker compose up -d --build      # 更新并重建
```

安装日志保存在项目的 `.runtime` 目录，该目录不会提交到 Git。

## 常见问题

### 检测提示未启用虚拟化

进入 BIOS/UEFI，启用 Intel Virtualization Technology（VT-x）或 SVM/AMD-V。仅在 Windows 功能中勾选“虚拟机平台”不能替代固件虚拟化。

### Windows 版本不符合要求

先通过 Windows Update 升级。`wsl --install` 的简化安装流程要求 Windows 10 Build 19041 或更高版本；更早版本不由本自动化脚本支持。

### 国内 Docker 镜像不可用

公共镜像可用性会变化。编辑 `.env`，把 `MYSQL_IMAGE`、`PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE` 改为可用的组织内部镜像或官方镜像，然后重新执行：

```powershell
.\install-wsl-docker-cn.ps1
```

### 端口 5291 被占用

检查监听进程：

```powershell
Get-NetTCPConnection -LocalPort 5291 -State Listen
```

停止冲突程序后重新运行安装脚本。本项目对外端口固定为 `5291`。

### 重跑是否会清空数据

不会。脚本是幂等的，现有 `.env` 和 Docker 数据卷会保留。除非明确执行 `docker compose down -v`，否则 MySQL 和保存文件不会被删除。

## 参考依据

- [Microsoft：安装 WSL](https://learn.microsoft.com/zh-cn/windows/wsl/install)
- [Microsoft：旧版本 WSL 的手动安装步骤与 WSL2 要求](https://learn.microsoft.com/zh-cn/windows/wsl/install-manual)
- [Docker：在 Ubuntu 安装 Docker Engine](https://docs.docker.com/engine/install/ubuntu/)
- [Docker：安装 Compose 插件](https://docs.docker.com/compose/install/linux/)
- [清华大学 TUNA：Docker CE 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/docker-ce/)
- [清华大学 TUNA：PyPI 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)
