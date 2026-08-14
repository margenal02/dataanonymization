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

_SINGLE_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗"
    "山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸"
    "司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党"
    "翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄"
    "晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文"
    "寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙"
    "乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
_COMPOUND_SURNAMES = (
    "欧阳|太史|端木|上官|司马|东方|独孤|南宫|万俟|闻人|夏侯|诸葛|尉迟|"
    "公羊|赫连|澹台|皇甫|宗政|濮阳|公冶|太叔|申屠|公孙|慕容|仲孙|钟离|"
    "长孙|宇文|司徒|鲜于|司空|闾丘|子车|亓官|司寇|巫马|公西|颛孙|壤驷|"
    "公良|漆雕|乐正|宰父|谷梁|拓跋|夹谷|轩辕|令狐|段干|百里|呼延|东郭|南门"
)
_SURNAME = rf"(?:{_COMPOUND_SURNAMES}|[{_SINGLE_SURNAMES}])"
_PERSON_NAME = rf"(?:{_SURNAME}[\u4e00-\u9fff]{{1,2}}|[\u4e00-\u9fff]{{1,6}}·[\u4e00-\u9fff·]{{1,12}})"

_PERSON_STOPWORDS = {
    "人员", "姓名", "联系人", "负责人", "经办人", "审核人", "审批人", "申请人",
    "采购人", "招标人", "供应商", "管理员", "操作员", "制表人", "复核人", "签字人",
    "办公室", "委员会", "有限公司", "总公司", "分公司", "研究院", "研究所", "服务中心",
    "北京市", "天津市", "上海市", "重庆市", "合格", "不合格", "同意", "不同意",
    "项目", "方案", "申请", "费用", "单价", "合计", "金额", "部门", "单位", "名称",
    "规格", "型号", "数量", "备注", "日期", "时间", "状态", "结果", "意见", "内容",
    "合同", "采购", "招标", "中标", "烟草", "公司", "地址", "手机", "电话", "邮箱",
    "传真", "附件", "正文", "标题", "序号", "说明", "管理", "支持", "记录", "文件",
    "网络", "系统", "环境", "安全", "处理", "完成",
}

_ORG_SUFFIX = (
    r"烟草专卖局|烟草公司|卷烟厂|烟叶复烤厂|复烤厂|有限责任公司|股份有限公司|"
    r"集团有限公司|集团公司|总公司|分公司|有限公司|研究院|研究所|委员会|"
    r"管理局|财政局|公安局|税务局|专卖局|办公室|物流中心|营销中心|技术中心|"
    r"服务中心|银行|协会|学校|医院|工厂|中心|公司"
)
_ORG_CHARS = r"[\u4e00-\u9fffA-Za-z0-9（）()·&＆\-]"
_PROVINCE = (
    r"北京市|天津市|上海市|重庆市|河北省|山西省|辽宁省|吉林省|黑龙江省|江苏省|"
    r"浙江省|安徽省|福建省|江西省|山东省|河南省|湖北省|湖南省|广东省|海南省|"
    r"四川省|贵州省|云南省|陕西省|甘肃省|青海省|台湾省|内蒙古自治区|广西壮族自治区|"
    r"西藏自治区|宁夏回族自治区|新疆维吾尔自治区|香港特别行政区|澳门特别行政区"
)

PATTERNS = {
    "organization": [
        # 烟草行业常见的多层级全称优先，避免只截取到中间的“烟草公司”。
        re.compile(
            r"([\u4e00-\u9fff]{2,16}(?:省|市|自治区)?烟草公司"
            r"[\u4e00-\u9fff]{1,16}(?:市|州|县|区)?公司)"
        ),
        re.compile(
            rf"({_ORG_CHARS}{{2,60}}?(?:中烟工业有限责任公司|"
            rf"烟草(?:（集团）|\(集团\))?(?:有限责任公司|股份有限公司|有限公司)))"
        ),
        re.compile(
            rf"(?:单位|机构|供应商|客户|甲方|乙方|采购人|招标人|中标人|承办单位|"
            rf"建设单位|实施单位|所属单位)\s*(?:[：:]|为|是)?\s*({_ORG_CHARS}{{2,70}}?(?:{_ORG_SUFFIX}))"
        ),
        re.compile(
            r"(?:部门|处室|承办部门|责任部门|经办部门)\s*(?:[：:]|为|是)?\s*"
            r"([\u4e00-\u9fff]{2,20}(?:部|处|科|室|中心))"
        ),
        re.compile(
            r"([\u4e00-\u9fff]{2,16}(?:管理部|业务部|财务部|人力资源部|审计部|审计处|"
            r"专卖处|法规处|办公室))"
        ),
        re.compile(rf"({_ORG_CHARS}{{2,70}}?(?:{_ORG_SUFFIX}))"),
    ],
    "person": [
        re.compile(
            rf"(?:项目负责人|法定代表人|联系人|经办人|负责人|审核人|审批人|复核人|"
            rf"申请人|填报人|制表人|签字人|姓名)\s*(?:[：:]|为|是)?\s*({_PERSON_NAME})"
            rf"(?=[ \t]*(?:[\r\n，,；;。.!！、/（）()]|$|电话|手机|负责|经办|审核|审批|复核|签字|填报))"
        ),
        re.compile(
            rf"({_PERSON_NAME})(?:同志)?\s*(?=负责|经办|审核|审批|复核|签字|签章|填报|担任|作为联系人)"
        ),
    ],
    "phone": [
        re.compile(r"(?<!\d)(1[3-9](?:[\s-]?\d){9})(?!\d)"),
        re.compile(r"(?<!\d)(0\d{2,3}[\s—-]?\d{7,8})(?!\d)"),
        re.compile(r"(?<!\d)(400[\s-]?\d{3}[\s-]?\d{4})(?!\d)"),
    ],
    "id_card": [
        re.compile(r"(?<![0-9A-Za-z])(\d{17}[0-9Xx]|\d{15})(?![0-9A-Za-z])"),
        re.compile(r"(?<![0-9A-Z])([159Y][0-9ABCDEFGHJKLMNPQRTUWXY]{17})(?![0-9A-Z])", re.I),
        re.compile(r"(?:护照|证件号码?|许可证号?)\s*[：:]?\s*([A-Z][0-9]{7,8})(?![0-9A-Z])", re.I),
    ],
    "email": [re.compile(r"(?<![\w.])([\w.+-]+@[\w-]+(?:\.[\w-]+)+)(?![\w.])", re.I)],
    "address": [
        re.compile(r"(?:地址|住址|办公地点|注册地址|通信地址|送货地点|收货地址)\s*(?:[：:]|为|是)?\s*([^\n\r，,；;。]{5,100})"),
        re.compile(
            rf"((?:{_PROVINCE})"
            r"(?:[\u4e00-\u9fff]{2,10}(?:市|州|盟))?"
            r"[\u4e00-\u9fff]{2,10}(?:区|县|旗|自治县)"
            r"[\u4e00-\u9fffA-Za-z0-9（）()\-]{1,50}(?:路|街|道|巷|大道|胡同|村|镇)"
            r"[\u4e00-\u9fffA-Za-z0-9号栋室层单元座\-]{0,30})"
        ),
        re.compile(
            r"(?:送货至|收货地为|收货地点|寄往|位于|办公地为)\s*"
            r"([\u4e00-\u9fff]{2,10}(?:市|州|盟)"
            r"[\u4e00-\u9fff]{2,10}(?:区|县|旗|自治县)"
            r"[\u4e00-\u9fffA-Za-z0-9（）()\-]{1,50}(?:路|街|道|巷|大道|胡同|村|镇)"
            r"[\u4e00-\u9fffA-Za-z0-9号栋室层单元座\-]{0,30})"
        ),
    ],
}

_PERSON_LIST = re.compile(
    r"(?:参会人员|人员名单|项目成员|联系人名单|经办人员|审核人员|审批人员)\s*[：:]\s*([^\n\r；;。]{2,120})"
)
_PERSON_NAME_RE = re.compile(_PERSON_NAME)
_PERSON_WHOLE_RE = re.compile(rf"^{_PERSON_NAME}$")
_PERSON_LINE_RE = re.compile(rf"(?m)^[ \t]*({_PERSON_NAME})[ \t]*$")
_ORG_LEADING_NOISE = re.compile(
    r"^(?:(?:本项目|该项目|本合同|该合同|项目|合同|协议|我司|本公司|本单位|贵公司)?"
    r"(?:由|与|同|向|为|在|经|委托|交由)|"
    r"单位|机构|供应商|客户|甲方|乙方|采购人|招标人|中标人|承办单位|建设单位|"
    r"实施单位|所属单位|名称|全称)+\s*(?:[：:]|为|是)?\s*"
)


def _is_cjk_or_ascii_word(character):
    return bool(character and ("\u4e00" <= character <= "\u9fff" or character.isalnum()))


def _matching_views(text):
    """Yield original and PDF-style de-spaced text with indexes back to the source."""
    yield text, list(range(len(text)))
    compact = []
    indexes = []
    changed = False
    following_nonspace = [""] * len(text)
    following = ""
    for index in range(len(text) - 1, -1, -1):
        character = text[index]
        if character in "\r\n":
            following = ""
        following_nonspace[index] = following
        if not character.isspace():
            following = character
    previous = ""
    for index, character in enumerate(text):
        if character in "\r\n":
            compact.append(character)
            indexes.append(index)
            previous = ""
            continue
        if character.isspace():
            if _is_cjk_or_ascii_word(previous) and _is_cjk_or_ascii_word(following_nonspace[index]):
                changed = True
                continue
        compact.append(character)
        indexes.append(index)
        if not character.isspace():
            previous = character
    if changed:
        yield "".join(compact), indexes


def _source_span(text, indexes, start, end):
    if start >= end or start >= len(indexes):
        return None
    source_start = indexes[start]
    source_end = indexes[end - 1] + 1
    return source_start, source_end, text[source_start:source_end]


def _clean_organization(value):
    cleaned = value.strip()
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = _ORG_LEADING_NOISE.sub("", cleaned).strip()
    cleaned = re.sub(r"^[与同向及、\s]+", "", cleaned)
    return cleaned


def _is_likely_person_name(value):
    compact = re.sub(r"\s+", "", value).strip("，,；;。.!！、/（）()")
    if not _PERSON_WHOLE_RE.fullmatch(compact):
        return False
    if compact in _PERSON_STOPWORDS:
        return False
    return not re.search(r"(?:公司|集团|中心|单位|部门|项目|系统|地址|电话|人员)$", compact)


class MappingBuilder:
    def __init__(self, task_salt, enabled_categories=None, custom_entities=None):
        self.task_salt = task_salt.upper()[:4]
        self.enabled = tuple(dict.fromkeys(enabled_categories or DEFAULT_CATEGORIES))
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
        # A manually supplied longer term has priority over an automatic substring.
        if any(original in known for known in self.original_to_token):
            return None
        self.counters[category] += 1
        label = CATEGORY_LABELS.get(category, CATEGORY_LABELS["custom"])
        token = f"【{label}_{self.task_salt}_{self.counters[category]:03d}】"
        self.original_to_token[original] = token
        self.token_to_original[token] = original
        self.token_categories[token] = category
        return token

    def _pattern_candidates(self, text):
        candidates = []
        seen = set()
        for view, indexes in _matching_views(text):
            for category in self.enabled:
                for pattern in PATTERNS.get(category, []):
                    for match in pattern.finditer(view):
                        group = 1 if match.lastindex else 0
                        span = _source_span(text, indexes, *match.span(group))
                        if not span:
                            continue
                        start, end, value = span
                        if category == "organization":
                            cleaned = _clean_organization(value)
                            if cleaned != value:
                                offset = value.find(cleaned)
                                if offset >= 0:
                                    start += offset
                                    value = cleaned
                            if len(re.sub(r"\s+", "", value)) < 3:
                                continue
                        if category == "person" and not _is_likely_person_name(value):
                            continue
                        key = (start, end, category, value)
                        if key not in seen:
                            seen.add(key)
                            candidates.append((start, end, category, value))

            if "person" in self.enabled:
                for list_match in _PERSON_LIST.finditer(view):
                    for name_match in _PERSON_NAME_RE.finditer(list_match.group(1)):
                        start_in_view = list_match.start(1) + name_match.start()
                        end_in_view = list_match.start(1) + name_match.end()
                        span = _source_span(text, indexes, start_in_view, end_in_view)
                        if span and _is_likely_person_name(span[2]):
                            key = (span[0], span[1], "person", span[2])
                            if key not in seen:
                                seen.add(key)
                                candidates.append(key)
                for line_match in _PERSON_LINE_RE.finditer(view):
                    span = _source_span(text, indexes, *line_match.span(1))
                    if span and _is_likely_person_name(span[2]):
                        key = (span[0], span[1], "person", span[2])
                        if key not in seen:
                            seen.add(key)
                            candidates.append(key)

        if "person" in self.enabled:
            stripped = text.strip()
            if _is_likely_person_name(stripped):
                start = text.find(stripped)
                candidates.append((start, start + len(stripped), "person", stripped))
        return candidates

    def discover(self, text):
        candidates = self._pattern_candidates(text)
        # Prefer the longest candidate when rules overlap (for example a full tobacco
        # company name that also contains a shorter generic “company” match).
        selected = []
        occupied = set()
        for start, end, category, value in sorted(
            candidates, key=lambda item: (-(item[1] - item[0]), item[0], DEFAULT_CATEGORIES.index(item[2]))
        ):
            positions = set(range(start, end))
            if positions & occupied:
                continue
            selected.append((start, category, value))
            occupied.update(positions)
        for _, category, value in sorted(selected, key=lambda item: item[0]):
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
