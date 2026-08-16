# 本地识别模型升级建议

## 结论

当前已采用 UIE-base 与 PP-StructureV3 精简模式。UIE-base 提升语义实体召回；精简 OCR 只负责扫描页的版面、文字检测和文字识别，不启用表格结构、公式、印章、图表、矫正或区域检测。系统仍采用强制人工确认：机器只提出候选，人工决定哪些内容真正脱敏。

推荐按以下顺序升级，而不是先增加 Agent：

1. 保留规则、精确词库和强制人工确认，建立烟草真实文档评测集。
2. 保持 PP-StructureV3 精简模式，用 `PP-DocLayout-S`、`PP-OCRv5_mobile_det` 和 `PP-OCRv5_mobile_rec` 处理扫描页；一个文件结束后退出 OCR 子进程，避免与 UIE-base 叠加占用内存。官方说明见 [PP-StructureV3 使用教程](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/PP-StructureV3.html)。
3. 使用人工确认数据离线批量微调 UIE-base。PaddleNLP 官方列出的 UIE-base 为 12 层、768 隐藏维度，并支持自定义训练，见 [PaddleNLP Taskflow 信息抽取说明](https://paddlenlp.readthedocs.io/en/latest/model_zoo/taskflow.html)。模型变更前应在目标 CPU/GPU 上测试内存、延迟和召回率。
4. 如果仍需第二意见，可部署开放权重的本地中文指令模型，让它输出“原文中逐字存在的候选片段 + 类型”，与 UIE/规则取并集后进入同一人工确认页。生成式模型不得直接改写原文，也不得直接决定最终脱敏。

## 为什么不推荐“本地 Claude Agent”

如果“clow”指 Claude：Anthropic 官方提供的是 Claude API/开发平台接入，不提供可下载后离线部署的 Claude 模型权重，见 [Anthropic Claude 开发文档](https://docs.anthropic.com/en/docs/welcome)。把敏感原文发送给云端 API 也与本项目“仅本地处理”的边界冲突。

Agent 是流程编排方式，不是识别模型。它可以依次调用 OCR、规则、UIE、本地大模型和人工确认接口，但不会凭空提升底层 OCR 或实体模型的准确率；更多自主步骤还会增加不可预测输出和审计难度。

## 上线验收指标

- 以真实烟草文档建立独立测试集，至少覆盖人名、单位/部门、产品、产区、地址和表格/多栏扫描件。
- 首要指标使用召回率（漏报），同时记录精确率（误报）和每页耗时。
- 模型升级只在测试集召回率明显提升、误报可由人工复核承受、目标主机资源稳定时启用。
- 人工确认结果继续加密留存，定期人工清洗后再批量训练；不能把未经复核的自动候选直接作为正样本。
