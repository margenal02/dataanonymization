import re
from collections import Counter


CATEGORY_LABELS = {
    "organization": "单位",
    "person": "人名",
    "phone": "电话",
    "id_card": "证件",
    "email": "邮箱",
    "address": "地址",
    "custom": "敏感项",
}

DEFAULT_CATEGORIES = ["organization", "person", "phone", "id_card", "email", "address"]

PATTERNS = {
    "organization": [
        re.compile(r"(?:单位|公司|机构|供应商|客户|甲方|乙方|采购人|招标人)\s*[：:]\s*([\u4e00-\u9fffA-Za-z0-9（）()·]{3,50}(?:烟草专卖局|烟草公司|卷烟厂|有限责任公司|股份有限公司|有限公司|集团公司|总公司|集团|分公司|专卖局|研究院|研究所|中心|公司))"),
        re.compile(r"(?<![\u4e00-\u9fffA-Za-z0-9])([\u4e00-\u9fffA-Za-z0-9（）()·]{2,40}(?:烟草专卖局|烟草公司|卷烟厂|有限责任公司|股份有限公司|有限公司|集团公司|总公司|分公司|专卖局|研究院|研究所))(?![\u4e00-\u9fffA-Za-z0-9])"),
    ],
    "person": [
        re.compile(r"(?:姓名|联系人|经办人|负责人|审核人|审批人|法定代表人|项目经理|制表人)\s*[：:]\s*([\u4e00-\u9fff·]{2,6})"),
    ],
    "phone": [
        re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"),
        re.compile(r"(?<!\d)(0\d{2,3}[-—]?\d{7,8})(?!\d)"),
    ],
    "id_card": [re.compile(r"(?<![0-9A-Za-z])(\d{17}[0-9Xx]|\d{15})(?![0-9A-Za-z])")],
    "email": [re.compile(r"(?<![\w.])([\w.+-]+@[\w-]+(?:\.[\w-]+)+)(?![\w.])", re.I)],
    "address": [re.compile(r"(?:地址|住址|办公地点|注册地址)\s*[：:]\s*([^\n\r，,；;]{5,80})")],
}


class MappingBuilder:
    def __init__(self, task_salt, enabled_categories=None, custom_entities=None):
        self.task_salt = task_salt.upper()[:4]
        self.enabled = set(enabled_categories or DEFAULT_CATEGORIES)
        self.original_to_token = {}
        self.token_to_original = {}
        self.token_categories = {}
        self.counters = Counter()
        for item in custom_entities or []:
            text = item.get("text", "").strip()
            category = item.get("category", "custom")
            if text:
                self.register(text, category if category in CATEGORY_LABELS else "custom")

    def register(self, original, category):
        original = original.strip()
        if len(original) < 2 or original in self.original_to_token or "【" in original:
            return self.original_to_token.get(original)
        self.counters[category] += 1
        label = CATEGORY_LABELS.get(category, CATEGORY_LABELS["custom"])
        token = f"【{label}_{self.task_salt}_{self.counters[category]:03d}】"
        self.original_to_token[original] = token
        self.token_to_original[token] = original
        self.token_categories[token] = category
        return token

    def discover(self, text):
        for category in self.enabled:
            for pattern in PATTERNS.get(category, []):
                for match in pattern.finditer(text):
                    value = match.group(1) if match.lastindex else match.group(0)
                    self.register(value, category)

    def anonymize(self, text):
        if not text:
            return text
        self.discover(text)
        result = text
        for original in sorted(self.original_to_token, key=len, reverse=True):
            result = result.replace(original, self.original_to_token[original])
        return result

    def export(self):
        return {
            "version": 1,
            "token_to_original": self.token_to_original,
            "token_categories": self.token_categories,
        }

    def counts(self):
        return {CATEGORY_LABELS.get(key, key): value for key, value in self.counters.items()}


def restore_text(text, mapping):
    result = text
    for token, original in sorted(mapping.get("token_to_original", {}).items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(token, original)
    return result
