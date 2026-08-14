# Windows + WSL2 + Docker 中国大陆一键安装说明

本项目只需一个 Windows PowerShell 脚本 `install-wsl-docker-cn.ps1`，检测与安装已合并。直接运行后，脚本先执行只读系统检测；只有检测合格才询问是否继续。选择“是”后，它会继续检查现有 WSL、Ubuntu、Docker Engine 与 Compose，符合版本范围的组件会明确显示“跳过安装”，只补装或升级缺失、过旧的组件，最后完成国内镜像配置、安全密钥生成、容器部署、WSL 常驻任务和持续健康检查。脚本执行时会在已忽略的 `.runtime` 目录临时展开 WSL 命令，成功后自动删除，不需要附带第二个安装脚本。

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

Windows 10 家庭版、专业版、企业版和教育版只要达到上述版本并支持 WSL2，均可使用。WSL 本身是 Windows 签名系统组件，仍从 Microsoft 官方服务安装；Ubuntu APT、Docker CE 和 PyPI 会在清华、阿里云、USTC、华为云、腾讯云、北外 BFSU 与南京大学 NJU 之间实测并选择最快可用源。npm 会在 npmmirror、华为云和腾讯云中选择最快候选，国内候选全部不可用时再回退官方源；应用基础容器也优先使用中国大陆镜像。

脚本默认部署 Ubuntu 24.04、Python 3.13、Django 5.2、MySQL 8.4、Node.js 22 和 Nginx 1.27。组件兼容范围如下：

| 组件 | 支持范围 | 已符合范围时 | 低于范围时 | 高于范围时 |
|---|---|---|---|---|
| WSL 运行时 | `>= 0.67.6`（systemd 最低要求） | 跳过更新 | 下载并安装微软签名的稳定版 MSI | 保留现有版本 |
| Ubuntu | Ubuntu 24.04，且运行于 WSL2 | 跳过安装/转换 | 安装或转换为 WSL2 | 不适用 |
| Docker Engine | `>= 24.0` 且 `< 30.0`，即 24.x–29.x | 跳过安装 | 升级到镜像仓库稳定版 | 停止并提示，不自动降级 |
| Docker Compose | `>= 2.20` 且 `< 6.0`，即 v2.20–v5.x | 跳过安装 | 升级到镜像仓库稳定版 | 停止并提示，不自动降级 |

上述上限是安装脚本采用的保守自动部署边界，并不表示更高版本一定不能运行。超出上限时停止，是为了避免安装脚本在未验证的新主版本上修改现有环境。

最开始的系统资源检测会显示 `系统检测 1/10` 至 `系统检测 10/10`，依次检查 Windows 版本、内存与虚拟机信息、处理器虚拟化、项目磁盘、端口 5291、两个 Windows 功能，并为软件包、npm 和容器镜像选择可用来源。WMI 与端口单项最长等待 15 秒，DISM Windows 功能检查单项最长等待 45 秒；镜像候选超时后自动尝试下一个，不再因为单个公共镜像不可访问而终止。每项开始、完成、失败及最终选择都会写入固定支持日志。

选择继续安装后，现有环境检测会明确显示“WSL 运行时版本、WSL 发行版、发行版版本、Docker/Compose”四个子步骤。WSL 版本和发行版查询各最多等待 12 秒，Docker/Compose 查询最多等待 20 秒；命令超时会结束本次只读检测，按“未安装或版本不可识别”继续，不会无限停在“检测主机现有的 WSL、Ubuntu 与 Docker”。

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

脚本需要管理员权限；如果从普通 PowerShell 启动，会自动打开管理员窗口。该窗口在检测或安装结束后保持打开，便于查看结果和错误日志，可确认完成后手动关闭。部署完成时脚本会创建并立即启动 Windows 计划任务 `DataAnonymizationWslKeepAlive`：该任务在当前用户登录后自动启动 WSL、Docker 和本项目，并用一个不含密码或密钥的常驻进程避免 WSL 因空闲退出。任务没有执行时限，在使用电池时也不会被系统自动停止。

首次启用 WSL2 时需要重启 Windows。脚本会写入一次性的 `RunOnce` 续跑项；手动重启并登录原管理员账号后，安装会自动继续，且不会重复询问是否安装。全部完成后续跑项会自动清除。

如果希望脚本在启用 WSL2 后自动重启：

```powershell
.\install-wsl-docker-cn.ps1 -AutoReboot
```

自动重启有 15 秒缓冲时间，可运行 `shutdown /a` 取消。

## WSL 下载通道与进度

WSL 运行时和 Ubuntu 发行版属于 Windows 系统组件。微软没有公布可验证的中国大陆 WSL 系统包镜像；脚本不会从第三方网站下载或安装系统级 WSL 包。Ubuntu APT、Docker CE、PyPI、npm 和应用容器仍使用下一节列出的大陆镜像。

默认使用 `Auto`：先读取微软 WSL 官方发布元数据，再调用 Windows 10/11 自带的原生 `curl.exe`，直接下载最新稳定版、与处理器架构匹配的微软 WSL MSI，并从微软官方发行版清单下载 Ubuntu `.wsl` 文件。下载 WSL MSI 前会对 GitHub 官方直连及两个大陆反向代理各做最多 1 MB 实际取样，验证 MSI 文件头后选择当前机器上最快的通道。即使 GitHub 网页探测失败，也仍会尝试可用的加速传输；只有官方元数据或全部下载路径失败时才回退 Microsoft Store。代理只传输公开文件，最终仍必须通过 GitHub 官方 SHA-256 和微软数字签名校验。

脚本每 0.5 秒读取断点文件的实际增长量，因此可以显示真实下载大小、百分比、瞬时速度和平均速度；即使暂时没有新字节，也会显示 `实时 0.00 MB/s`。下载状态使用按当前窗口宽度自动裁剪的单行进度条原地刷新，不使用会覆盖控制台历史区的 Windows PowerShell `Write-Progress`；阶段完成后才保留一条最终结果。Web 直连失败时才自动切换 Microsoft Store 系统通道；系统缺少 `curl.exe` 时自动回退到 .NET 下载器。

如果 GitHub 官方发布 API 暂时无法访问，脚本会使用内置的、带官方 URL、文件大小和 SHA-256 的已验证稳定版元数据继续测速下载；API 恢复后仍动态选择微软最新稳定版。内置兜底不会跳过 SHA-256 或微软数字签名验证。

下载文件保存在 `.runtime/downloads`。中断时保留 `.part` 断点文件，重新运行后自动续传；已经完整下载的同版本文件直接复用，不重复下载。WSL MSI 会校验 GitHub 发布接口给出的 SHA-256（如接口提供）及微软 Authenticode 数字签名；Ubuntu 包会校验微软官方清单中的 SHA-256。任何校验失败的文件都会被立即删除并拒绝安装。

也可以在启动时固定通道；固定后不会自动切换：

```powershell
# 明确使用 GitHub 官方 Web 通道
.\install-wsl-docker-cn.ps1 -WslDownloadChannel Web

# 组织网络无法访问 GitHub 时，固定使用 Microsoft Store
.\install-wsl-docker-cn.ps1 -WslDownloadChannel Store

# 设置低速/无进展判定时间（允许范围 30～600 秒）
.\install-wsl-docker-cn.ps1 -WslNoProgressTimeoutSeconds 90
```

安装窗口使用同一个动态进度区域显示总进度，下面是区域内状态文字的示例：

```text
[#########---------------------]  32%  下载微软官方 WSL 安装包 - 47%｜121.8 MB / 259.0 MB｜实时 3.42 MB/s｜平均 3.18 MB/s
```

Web 直连的进度由 HTTP 响应中的总大小和实际写入磁盘的字节数计算，每 0.5 秒在同一个进度区域内刷新一次；速度由对应时间窗口内的实际字节增量计算，不根据时间虚构。固定使用 `Store` 时，下载由 Windows 系统组件接管；如果系统通道不返回字节数据，脚本只能显示阶段状态，无法计算可靠的 MB/s。

## 自动配置的镜像

| 依赖 | 自动选择顺序 |
|---|---|
| Ubuntu APT、Docker CE、Python / Django | 清华大学 TUNA、阿里云、USTC、华为云、腾讯云、北外 BFSU、南京大学 NJU：用 `curl.exe` 小流量实测，选择最快可用源 |
| npm 包 | npmmirror、华为云、腾讯云：选择最快可用国内源；全部不可用时回退 npm 官方源 |
| Python、MySQL、Node、Nginx 容器 | DaoCloud 公共镜像代理 → Docker Hub 官方地址 |
| Docker Hub 加速 | 选择 DaoCloud 时启用；回退官方地址时不写入无效加速项 |

脚本会把检测选中的实际地址写入 WSL 配置和 `.env`，不是只在检测阶段临时放行；已有 `.env` 的密码与密钥保持不变，只更新镜像相关字段，确保失败后重试也能应用新选择。国内公共镜像属于外部依赖，服务地址可能调整。生产环境建议将所需镜像同步到组织自有的 Harbor/制品库，并将 `.env` 中的四个镜像地址改为内部地址。

## 安全配置

首次部署且项目中不存在 `.env` 时，脚本使用 OpenSSL 随机生成：

- Django 应用密钥；
- 匿名映射加密密钥；
- MySQL root 密码；
- MySQL 应用账号密码。

脚本会同时设置 WSL 文件权限和 Windows NTFS ACL，仅保留当前管理员、SYSTEM 和本机管理员组权限。请离线备份 `MAPPING_ENCRYPTION_KEY`；该密钥丢失后，已保存任务无法反匿名。脚本不会覆盖已有 `.env`，如果其中仍含示例弱密钥则会拒绝部署。如果脚本生成的 `.env` 与已初始化 MySQL 数据卷密码不一致，部署程序只同步 MySQL root 与应用账号密码，不修改 Django 密钥、映射加密密钥或业务数据。

本应用按需求无需登录，因此请勿把 `5291` 直接暴露到互联网。建议只允许可信办公内网访问，并在正式环境通过组织网关增加 HTTPS、身份认证和访问审计。

## 安装后操作

首选访问地址：<http://127.0.0.1:5291>

备用访问地址：<http://localhost:5291>

安装脚本不会在第一次请求成功后立即结束，而会从 Windows 对两个地址执行至少 5 次连续健康检查。连续约 15 秒均可访问、且 `DataAnonymizationWslKeepAlive` 仍处于运行状态时，才会显示“安装和部署全部完成”。微软明确说明，systemd 服务本身不会使 WSL 实例保持运行，因此请勿删除或停止这个计划任务。

查看常驻任务状态：

```powershell
Get-ScheduledTask -TaskName DataAnonymizationWslKeepAlive
```

如果该任务被手工停止，可重新启动：

```powershell
Start-ScheduledTask -TaskName DataAnonymizationWslKeepAlive
```

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

安装支持日志固定写入项目下的 `.runtime/install-support-latest.log`，该目录不会提交到 Git。安装失败、窗口异常或需要协助排查时，直接把这一个文件发送给维护人员即可，不需要截图或猜测哪份日志最新。日志持续写入磁盘，因此 PowerShell 被强制关闭时仍会保留终止前的内容；下次启动脚本前，会把没有正常结束标记的旧日志另存为 `install-wsl-docker-recovered-时间.log`，避免被覆盖。每次正常结束或捕获到错误后，也会保存 `install-wsl-docker-时间.log` 历史归档。

日志包含脚本 SHA-256、PowerShell/Windows 信息、安装参数、各步骤状态、Docker 最近输出、容器退出码、健康检查和异常调用栈。脚本不会主动输出 `.env` 中的密码、密钥或令牌；不要把 `.env` 文件一并发送。日志仍可能包含主机路径、局域网 IP、镜像名称和容器元数据，应按内部运维资料保护。

## 常见问题

### 检测提示未启用虚拟化

进入 BIOS/UEFI，启用 Intel Virtualization Technology（VT-x）或 SVM/AMD-V。仅在 Windows 功能中勾选“虚拟机平台”不能替代固件虚拟化。

### Windows 版本不符合要求

先通过 Windows Update 升级。`wsl --install` 的简化安装流程要求 Windows 10 Build 19041 或更高版本；更早版本不由本自动化脚本支持。

### 读取 WSL 版本时出现 NativeCommandError

请先更新到包含此修复的最新版脚本。旧版 Windows PowerShell 5.1 会把旧 WSL 输出的“请运行 `wsl.exe --update`”状态提示包装成 `NativeCommandError`；新版脚本会按退出码识别为待更新状态，然后继续执行 WSL 更新，不再把该提示误判为脚本异常。

### WSL 输出出现乱码

最新版安装脚本以带 BOM 的 UTF-8 保存，保证 Windows PowerShell 5.1 在执行前正确解析中文；同时会自动识别 `wsl.exe` 的 UTF-16、UTF-8 或 Windows 系统代码页输出。旧窗口需要按 `Ctrl+C` 退出，更新完整脚本后重新打开管理员 PowerShell 再运行。

### WSL 更新长时间停在 0%

最新版脚本的 `Auto`/`Web` 模式直接下载官方包，窗口会持续显示实际字节和 MB/s；网络中断后自动从 `.part` 文件续传，完整缓存不会重复下载。如果使用的是旧脚本，可按 `Ctrl+C` 停止，更新项目后重新运行。不要从不明第三方站点下载安装包。

### 卡在“检测主机现有的 WSL、Ubuntu 与 Docker”

旧版脚本调用 `wsl.exe --version`、`wsl.exe --list` 或启动发行版读取 Docker 版本时没有超时保护，WSL 服务异常可能造成窗口长时间无输出。最新版会显示具体检测项，并在 12～20 秒后结束失去响应的只读检测进程，然后继续安装。此步骤没有写入操作，旧窗口可以按 `Ctrl+C` 安全停止，更新脚本后重新运行。

### Ubuntu 安装后提示“不能对 Null 值表达式调用方法”

这是旧版脚本读取 `wslpath` 空输出时产生的错误，不代表已下载的 Ubuntu 损坏。更新到最新版脚本后直接重新运行即可：已安装的 Ubuntu 和完整下载缓存会被复用。新版会先检查 `wslpath` 的退出码和非空输出；若新安装的发行版暂时没有返回文字，则验证标准 `/mnt/<盘符>/...` 挂载路径后继续，不再对空值调用字符串方法。

### 国内 Docker 镜像不可用

最新版脚本会自动尝试清华、阿里云、USTC、华为云、腾讯云、北外 BFSU、南京大学 NJU、npmmirror、DaoCloud 以及必要的官方回退地址。软件包和 npm 检测使用 Windows 自带 `curl.exe`，会记录每个可用候选的响应时间并选择最快者；只有同一类别的所有候选均不可用时才停止。此时可编辑 `.env`，把 `MYSQL_IMAGE`、`PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE` 改为可用的组织内部镜像或官方镜像，然后重新执行：

```powershell
.\install-wsl-docker-cn.ps1
```

### 提示 `dependency failed to start` 或后端容器不健康

最新版脚本会分阶段启动 MySQL、前端、Django 后端和 Nginx，不再让 `docker compose up` 在依赖失败时隐藏根因。MySQL 健康检查会使用应用实际数据库账号执行 `SELECT 1`，后端健康检查也有独立启动缓冲。任一容器退出或超时，窗口及 `.runtime` 安装日志会自动显示容器状态、退出码、最近的健康检查结果和对应服务日志。

如果诊断信息提示 MySQL `ERROR 1045` 或 `Access denied`，通常是现有 `mysql_data` 数据卷的旧密码与当前 `.env` 不一致。最新版脚本会在首次发现 1045 后停止等待，验证 `.env` 使用的是脚本生成的 64 位十六进制随机密码，然后停止正常数据库容器，使用不开放网络、仅允许容器内部 Unix 套接字连接的临时维护容器，同步 root 与应用账号密码。同步完成后临时容器立即删除，原数据库卷、任务记录和业务表不会删除，部署会自动继续。

如果 `.env` 使用了人工设置的其他密码格式，脚本会安全停止而不会修改数据库。此时应恢复与数据卷匹配的原 `.env`，或由数据库管理员按组织流程手工重置密码；只有明确确认没有需要保留的数据时，才可按运维文档重建数据库卷。不要直接执行 `docker compose down -v` 处理密码错误。

容器部署阶段会显示 `步骤 1/11` 至 `步骤 11/11`，依次覆盖 Docker 启动、安全配置、基础镜像拉取、后端构建、前端构建、MySQL 启动与检查、Django 启动与检查、Nginx 启动和网站检查。同一小步骤耗时较长时，单行进度会每秒更新本步骤耗时、部署总耗时和最近一条 Docker 输出；数据库及后端健康检查还会显示当前检查次数、容器状态和健康状态。当前步骤同时写入 `.runtime` 下的临时状态文件，Docker 构建日志很大时也不会丢失步骤名称，流程结束后自动删除该文件。

### 端口 5291 被占用

检查监听进程：

```powershell
Get-NetTCPConnection -LocalPort 5291 -State Listen
```

停止冲突程序后重新运行安装脚本。本项目对外端口固定为 `5291`。

### 脚本显示完成，但关闭窗口后网页无法访问

旧版脚本只在部署命令刚结束时检查一次网站；WSL 随后因空闲退出时，浏览器会显示 `ERR_CONNECTION_REFUSED`。日志中容器和健康检查都成功、但脚本结束后端口消失，正是这一情况。微软的 WSL systemd 文档说明，systemd 服务不会自行保持 WSL 实例存活。

请更新项目并重新运行同一个一键脚本。新版会创建 `DataAnonymizationWslKeepAlive` 登录自动启动任务，并在脚本结束前做连续稳定性检查；重新运行不会删除 `.env`、MySQL 数据卷、任务记录或保存文件。完成后优先访问 <http://127.0.0.1:5291>。

### 重跑是否会清空数据

不会。脚本是幂等的，现有 `.env` 和 Docker 数据卷会保留。数据库密码不一致时只执行账号密码同步，不重建数据卷。除非明确执行 `docker compose down -v`，否则 MySQL 和保存文件不会被删除。

## 参考依据

- [Microsoft：安装 WSL](https://learn.microsoft.com/zh-cn/windows/wsl/install)
- [Microsoft：旧版本 WSL 的手动安装步骤与 WSL2 要求](https://learn.microsoft.com/zh-cn/windows/wsl/install-manual)
- [Microsoft：在 WSL 中使用 systemd（要求 WSL 0.67.6 或更高；systemd 服务不会保持 WSL 实例运行）](https://learn.microsoft.com/zh-cn/windows/wsl/systemd)
- [Microsoft：从 Windows 通过 localhost 访问 WSL 网络应用](https://learn.microsoft.com/zh-cn/windows/wsl/networking)
- [MySQL 8.4：`--skip-grant-tables` 与禁用远程连接](https://dev.mysql.com/doc/refman/8.4/en/server-options.html)
- [MySQL 8.4：`FLUSH PRIVILEGES` 重新加载权限表](https://dev.mysql.com/doc/refman/8.4/en/flush.html)
- [Docker 官方 MySQL 镜像：已有数据目录时初始化环境变量不会修改现有数据库](https://github.com/docker-library/docs/blob/master/mysql/README.md)
- [Docker：在 Ubuntu 安装 Docker Engine](https://docs.docker.com/engine/install/ubuntu/)
- [Docker：安装 Compose 插件](https://docs.docker.com/compose/install/linux/)
- [清华大学 TUNA：Docker CE 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/docker-ce/)
- [清华大学 TUNA：PyPI 镜像使用帮助](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)
- [阿里云：Docker CE 镜像](https://developer.aliyun.com/mirror/docker-ce/)
- [阿里云：PyPI 镜像](https://developer.aliyun.com/mirror/pypi)
- [中国科学技术大学 USTC：Docker CE 镜像](https://mirrors.ustc.edu.cn/help/docker-ce.html)
- [中国科学技术大学 USTC：PyPI 镜像](https://mirrors.ustc.edu.cn/help/pypi.html)
- [华为云开源镜像站](https://mirrors.huaweicloud.com/)
- [腾讯云软件源](https://mirrors.cloud.tencent.com/)
- [北京外国语大学 BFSU：Ubuntu 镜像](https://mirrors.bfsu.edu.cn/help/ubuntu/)
- [北京外国语大学 BFSU：Docker CE 镜像](https://mirrors.bfsu.edu.cn/help/docker-ce/)
- [北京外国语大学 BFSU：PyPI 镜像](https://mirrors.bfsu.edu.cn/help/pypi/)
- [南京大学开源镜像站](https://mirror.nju.edu.cn/)
