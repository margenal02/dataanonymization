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

## Windows + WSL2 + Docker 部署

Windows 10/11 中国大陆网络环境只需一个 `install-wsl-docker-cn.ps1`。脚本先检测系统，检测合格后询问是否继续；选择“是”后检查现有 WSL2、Ubuntu、Docker 和 Compose，版本符合要求时自动跳过重复安装。在管理员 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-wsl-docker-cn.ps1
```

如只做检测，可为同一脚本添加 `-CheckOnly`。完整流程、支持版本、国内镜像配置、重启续跑和故障排查参见 [Windows + WSL2 + Docker 中国大陆一键安装说明](docs/WSL_DOCKER_CN_INSTALL.md)。

安装完成后访问 [http://localhost:5291](http://localhost:5291)。日常运维统一进入 WSL2：

```powershell
wsl -d Ubuntu-24.04 -u root
```

进入 WSL 后切换到项目目录，再执行 Docker Compose 命令：

```bash
cd /mnt/d/code/dataanonymization  # 按实际项目路径修改
docker compose ps                 # 查看状态
docker compose logs -f            # 查看日志
docker compose down               # 停止服务，保留数据
docker compose up -d              # 重新启动
```

## Linux 主机 + Docker 部署

Linux 服务器无需 WSL，推荐 Ubuntu Server 22.04/24.04 LTS。Docker Engine 支持范围为 `>=24.0 且 <30.0`，Compose 插件为 `>=2.20 且 <6.0`；现有版本符合范围时无需重新安装。安装 Docker、配置中国大陆镜像、安全密钥、防火墙、启动与备份步骤参见 [Linux 主机 Docker 部署说明](docs/LINUX_DOCKER_DEPLOYMENT.md)。

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

仓库提供了一个不含真实敏感信息的验证文件：[烟草采购清单示例.txt](examples/烟草采购清单示例.txt)。

## 生产安全建议

本轮安全测试方法、结果和剩余风险参见 [本地安全与渗透测试报告](docs/PENETRATION_TEST_REPORT.md)。

- 将 `MAPPING_ENCRYPTION_KEY` 纳入密钥备份。该密钥丢失后，历史任务无法反匿名。
- 通过主机防火墙限制 `5291` 只对可信内网开放；需要跨网访问时在上层网关启用 HTTPS。
- 定期备份 MySQL 和 `media_data` Docker 卷，两者缺一都会影响历史任务恢复。
- 制定任务数据保留周期，并按组织制度清理原文件、处理稿、正式文件和数据库记录。
- 当前版本未内置账号权限；多人环境上线前应接入组织统一身份认证或在 Nginx 前增加访问控制。
