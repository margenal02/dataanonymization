# UIE 模型包导入导出说明

## 适用范围

“模型中心”用于迁移经过 PaddleNLP UIE 微调的本地检查点。它不是数据库备份功能：导出的 ZIP 只包含模型权重、模型配置、分词器文件和平台生成的完整性清单，不包含原始文档、人工标签原文、匿名映射、MySQL 数据或 `.env` 密钥。

因此，模型可以交给其他受信部署复用；但接收方不能使用模型包恢复本机已经脱敏的文件。反匿名仍必须依赖原任务所在机器的数据库、媒体文件和 `MAPPING_ENCRYPTION_KEY`。

## 可导入目录

把一个可供 PaddleNLP `Taskflow(..., task_path=目录)` 直接加载的检查点压缩成 ZIP。压缩包可以有一层公共根目录，去掉该目录后，根部至少应包含：

```text
model_state.pdparams       # 或其他 .pdparams / .pdiparams 权重
model_config.json          # 或 config.json
vocab.txt                  # 或 tokenizer.json / SentencePiece 模型
tokenizer_config.json      # 可选但建议保留
special_tokens_map.json    # 可选但建议保留
```

不要加入训练原文、数据库导出、日志、`.env`、Python 脚本或启动程序。平台拒绝 `.py`、`.exe`、`.dll`、`.so`、`.sh`、`.ps1` 等可执行内容。

## Web 操作

1. 打开左侧“模型”。
2. 在“导入训练权重”选择 ZIP，可填写显示名称和版本。
3. 点击“校验并导入模型”。系统检查路径穿越、符号链接、重复路径、文件数量、解压总量、异常压缩比以及权重/配置/词表是否齐全。
4. 在“模型版本”中点击“设为当前”。常驻模型会先释放，新权重在下一次识别时加载。
5. 点击下载图标导出标准模型包；在另一台同版本系统中重复导入即可。
6. 如需回退，选择内置 `uie-base` 并设为当前。当前正在使用的模型不能删除。

导入上限由 `.env` 的 `MODEL_PACKAGE_MAX_SIZE_MB` 控制，默认 1024 MB；普通业务文件仍由 `MAX_UPLOAD_SIZE_MB` 单独限制为 200 MB。调整后执行 `docker compose up -d --build` 使后端和 Nginx 配置生效。

## 完整性与兼容性

导入成功后，平台重新生成 `manifest.json`，记录包格式、基础模型、每个文件的大小和 SHA-256。激活和导出前会再次核验权重文件；文件被意外修改时会拒绝使用。

接收方应使用相同或兼容的 PaddlePaddle、PaddleNLP 版本与 CPU 架构。当前项目版本见 `backend/requirements.txt`。若外部微调脚本导出的目录无法被本项目的 `Taskflow` 加载，应先在同版本的隔离环境中完成一次推理自检，再导入生产部署。

模型权重可能记忆训练数据片段。只应使用经过脱敏或获准使用的训练语料，并在向第三方发送模型前完成组织内部的数据泄露评估和授权审批。
