# Windows + WSL2 + Docker 中国大陆一键安装说明

本项目只需一个 Windows PowerShell 脚本 `install-wsl-docker-cn.ps1`，检测与安装已合并。直接运行后，脚本先执行只读系统检测；只有检测合格才询问是否继续。选择“是”后，它会继续检查现有 WSL、Ubuntu、Docker Engine 与 Compose，符合版本范围的组件会明确显示“跳过安装”，只补装或升级缺失、过旧的组件，最后完成国内镜像配置、安全密钥生成、容器部署和健康检查。脚本执行时会在已忽略的 `.runtime` 目录临时展开 WSL 命令，成功后自动删除，不需要附带第二个安装脚本。

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

脚本默认部署 Ubuntu 24.04、Python 3.13、Django 5.2、MySQL 8.4、Node.js 22 和 Nginx 1.27。组件兼容范围如下：

| 组件 | 支持范围 | 已符合范围时 | 低于范围时 | 高于范围时 |
|---|---|---|---|---|
| WSL 运行时 | `>= 0.67.6`（systemd 最低要求） | 跳过更新 | 执行 `wsl --update` | 保留现有版本 |
| Ubuntu | Ubuntu 24.04，且运行于 WSL2 | 跳过安装/转换 | 安装或转换为 WSL2 | 不适用 |
| Docker Engine | `>= 24.0` 且 `< 30.0`，即 24.x–29.x | 跳过安装 | 升级到镜像仓库稳定版 | 停止并提示，不自动降级 |
| Docker Compose | `>= 2.20` 且 `< 6.0`，即 v2.20–v5.x | 跳过安装 | 升级到镜像仓库稳定版 | 停止并提示，不自动降级 |

上述上限是安装脚本采用的保守自动部署边界，并不表示更高版本一定不能运行。超出上限时停止，是为了避免安装脚本在未验证的新主版本上修改现有环境。

## 使用方法

1. 将完整项目目录复制或克隆到 Windows 本地磁盘。
2. 右键点击“Windows PowerShell”，选择“以管理员身份运行”，进入项目目录。
3. 执行唯一的一键脚本：

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install-wsl-docker-cn.ps1
   ```

4. 脚本先显示系统检测表。检测不合格时自动停止；检测合格时显示“是否继续安装和部署”，选择 `Yes（是）` 继续，选择 `No（否）` 则不做任何安装修改。

如只需要生成检测结果、不显示继续安装提示，可使用同一脚本的可选参数：

```powershell
.\install-wsl-docker-cn.ps1 -CheckOnly
```

脚本需要管理员权限；如果从普通 PowerShell 启动，会自动打开管理员窗口。该窗口在检测或安装结束后保持打开，便于查看结果和错误日志，可确认完成后手动关闭。

首次启用 WSL2 时需要重启 Windows。脚本会写入一次性的 `RunOnce` 续跑项；手动重启并登录原管理员账号后，安装会自动继续，且不会重复询问是否安装。全部完成后续跑项会自动清除。

如果希望脚本在启用 WSL2 后自动重启：

```powershell
.\install-wsl-docker-cn.ps1 -AutoReboot
```

自动重启有 15 秒缓冲时间，可运行 `shutdown /a` 取消。

## WSL 下载通道与进度

WSL 运行时和 Ubuntu 发行版属于 Windows 系统组件。微软官方只提供 Microsoft Store 和 `--web-download`（GitHub 官方发布）两种通道，没有公布可验证的中国大陆镜像；脚本不会从第三方网站下载或安装系统级 WSL 包。Ubuntu APT、Docker CE、PyPI、npm 和应用容器仍使用下一节列出的大陆镜像。

默认使用 `Auto`：先尝试 Microsoft Store 官方通道；如果该命令明确失败，自动切换 GitHub 官方 Web 通道。也可以在启动时固定通道：

```powershell
# Microsoft Store 较慢或 0% 长时间不动时，按 Ctrl+C 后改用 GitHub 官方通道
.\install-wsl-docker-cn.ps1 -WslDownloadChannel Web

# 组织网络无法访问 GitHub 时，固定使用 Microsoft Store
.\install-wsl-docker-cn.ps1 -WslDownloadChannel Store
```

安装窗口使用固定格式显示总进度：

```text
[############------------------]  40%  通过 Microsoft Store 官方通道更新 WSL
```

进度由已完成安装阶段和命令返回的真实百分比计算。WSL 返回下载百分比时，当前阶段会实时细分；Microsoft Store 未返回下载字节进度时，进度条会停在当前阶段起点并显示“等待安装程序返回进度”，不会根据时间虚构百分比。阶段完成后再跳到下一确定进度。

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

### 读取 WSL 版本时出现 NativeCommandError

请先更新到包含此修复的最新版脚本。旧版 Windows PowerShell 5.1 会把旧 WSL 输出的“请运行 `wsl.exe --update`”状态提示包装成 `NativeCommandError`；新版脚本会按退出码识别为待更新状态，然后继续执行 WSL 更新，不再把该提示误判为脚本异常。

### WSL 更新长时间停在 0%

如果进度条长时间停在“等待安装程序返回进度”，按 `Ctrl+C` 停止后运行 `.\install-wsl-docker-cn.ps1 -WslDownloadChannel Web`，使用微软文档提供的 GitHub 官方 Web 下载通道。不要从不明第三方站点下载安装包。

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
- [Microsoft：在 WSL 中使用 systemd（要求 WSL 0.67.6 或更高）](https://learn.microsoft.com/zh-cn/windows/wsl/systemd)
- [Docker：在 Ubuntu 安装 Docker Engine](https://docs.docker.com/engine/install/ubuntu/)
- [Docker：安装 Compose 插件](https://docs.docker.com/compose/install/linux/)
- [清华大学 TUNA：Docker CE 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/docker-ce/)
- [清华大学 TUNA：PyPI 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)
