# 隐数盾：烟草行业数据脱敏平台

面向内网部署的可逆数据脱敏应用。原始文件在本地完成敏感信息替换，脱敏稿可交由外部 AI 校对、总结或改写；AI 处理后的文件再上传本系统，使用原任务的加密映射恢复正式信息。

## 功能

- 支持 `.xls`、`.docx`、`.pdf`、`.ofd`、`.txt`。
- 自动识别单位/部门、人员姓名、电话、身份证、邮箱和地址。
- 支持手工补充烟草专卖局、卷烟厂、供应商和人员名单。
- 每个任务使用独立匿名标记，例如 `【单位_A1B2_001】`。
- 匿名映射使用 Fernet 对称加密后保存到 MySQL，不提供明文映射下载。
- 脱敏文件下载、原任务关联、反匿名恢复和任务历史均在同一工作台完成。
- 上传文件标题自动生成任务名称；每条记录保存原始上传、脱敏输出、反匿名上传稿和正式输出。
- 删除记录时同步删除该任务的全部保存文件和加密映射。
- Docker Compose 一键本地部署，对外端口固定为 `5291`。

## 技术结构

```text
浏览器 :5291
    │
  Nginx ── /api/* ── Django REST API ── MySQL 8
    │                         │
    └── Vue 3 + Bootstrap 5   └── 加密映射与本地文件处理
```

## 快速部署

### Windows + WSL2 中国大陆一键安装

Windows 10/11 中国大陆网络环境只需一个 `install-wsl-docker-cn.ps1`，它会按顺序完成系统检测、安装 WSL2、安装 Docker 和启动应用。在管理员 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-wsl-docker-cn.ps1 -CheckOnly
.\install-wsl-docker-cn.ps1
```

完整要求、国内镜像配置、重启续跑和故障排查参见 [Windows + WSL2 + Docker 中国大陆一键安装说明](docs/WSL_DOCKER_CN_INSTALL.md)。

### 已安装 Docker 的环境

前置条件：安装并启动 Docker Desktop（Linux 服务器安装 Docker Engine 与 Compose 插件）。

1. 复制环境文件：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 修改 `.env` 中以下值，不要沿用示例：

   - `DJANGO_SECRET_KEY`
   - `MAPPING_ENCRYPTION_KEY`
   - `MYSQL_ROOT_PASSWORD`
   - `MYSQL_PASSWORD`

   如果通过局域网 IP 访问，将服务器 IP 加到 `ALLOWED_HOSTS`，例如：

   ```dotenv
   ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20
   ```

3. 启动：

   ```powershell
   .\start.ps1
   ```

   或直接运行：

   ```powershell
   docker compose up -d --build
   ```

4. 浏览器访问 [http://localhost:5291](http://localhost:5291)。

### 未安装 Docker 时直接启动

Windows 开发机可以使用本地模式，仍然通过 `5291` 端口访问。该模式使用 SQLite，适合功能体验和开发调试：

```powershell
.\start-local.ps1
```

访问 [http://localhost:5291](http://localhost:5291)，停止服务运行：

```powershell
.\stop-local.ps1
```

正式内网部署仍建议使用上面的 Docker Compose 方式，以启用 MySQL 和 Nginx。

查看服务状态与日志：

```powershell
docker compose ps
docker compose logs -f
```

停止服务（数据卷仍保留）：

```powershell
.\stop.ps1
```

## 使用流程

1. 在“数据匿名”上传原文件，勾选识别类型，并在“指定敏感词”中补充行业专有单位或人员。
2. 下载脱敏文件，交由 AI 进行所需的内容处理。
3. 不要删除、拆分或改写文件中的 `【类别_任务码_序号】` 标记。
4. 返回“数据反匿名”，选择原脱敏任务，上传 AI 处理稿并下载正式文件。

指定敏感词每行一个；可用 `类型|内容` 标注：

```text
单位|某某市烟草专卖局
单位|某某卷烟厂
人名|张三
某内部项目代号
```

## 文件处理说明

PDF/OFD 的详细实现与限制参见 [PDF 与 OFD 处理机制说明](docs/FILE_PROCESSING_GUIDE.md)。

| 格式 | 处理方式 | 注意事项 |
|---|---|---|
| TXT | 保留检测到的文本编码，必要时转 UTF-8 BOM | 结构保真度最高 |
| DOCX | 处理正文、表格、页眉和页脚 | 跨多个富文本样式的敏感词会合并到首个样式段 |
| XLS | 保留工作簿和主要单元格样式 | 只处理文本单元格，不改写公式 |
| PDF | 提取文本后生成排版规范的新 PDF | 复杂版式不原样保留；扫描件必须先 OCR |
| OFD | 在 OFD 容器内替换 XML 文本 | 厂商扩展或图片型 OFD 可能需要先转文本型 OFD/OCR |

自动规则适合常见格式，但无法保证识别所有行业术语。正式使用前应维护本单位词表，并人工抽检脱敏文件，确认没有遗漏后再交给外部 AI。

## 开发与测试

后端默认在未配置 `MYSQL_HOST` 时使用 SQLite，便于开发；Docker 环境自动切换至 MySQL。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py runserver 8000
```

另一个终端运行前端：

```powershell
Set-Location frontend
npm ci
npm run dev
```

测试与构建：

```powershell
.\.venv\Scripts\python.exe backend\manage.py test anonymizer
Set-Location frontend
npm run build
```

仓库提供了一个不含真实敏感信息的验证文件：[烟草采购清单示例.txt](examples/烟草采购清单示例.txt)。

## 生产安全建议

本轮安全测试方法、结果和剩余风险参见 [本地安全与渗透测试报告](docs/PENETRATION_TEST_REPORT.md)。

- 将 `MAPPING_ENCRYPTION_KEY` 纳入密钥备份。该密钥丢失后，历史任务无法反匿名。
- 通过主机防火墙限制 `5291` 只对可信内网开放；需要跨网访问时在上层网关启用 HTTPS。
- 定期备份 MySQL 和 `media_data` Docker 卷，两者缺一都会影响历史任务恢复。
- 制定任务数据保留周期，并按组织制度清理原文件、处理稿、正式文件和数据库记录。
- 当前版本未内置账号权限；多人环境上线前应接入组织统一身份认证或在 Nginx 前增加访问控制。
