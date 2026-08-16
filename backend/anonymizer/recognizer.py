import re
import unicodedata
from collections import Counter


CATEGORY_LABELS = {
    "organization": "单位",
    "person": "人名",
    "product": "产品",
    "location": "产区",
    "phone": "电话",
    "id_card": "证件",
    "email": "邮箱",
    "address": "地址",
    "custom": "敏感项",
}

TOKEN_CODES = {
    "organization": "单",
    "person": "人",
    "product": "品",
    "location": "区",
    "phone": "电",
    "id_card": "证",
    "email": "邮",
    "address": "址",
    "custom": "敏",
}

DEFAULT_CATEGORIES = [
    "organization", "person", "product", "location", "phone", "id_card", "email", "address",
]

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
    "组长", "副组长", "组员", "成员", "主任", "副主任", "经理", "副经理",
    "部长", "副部长", "科长", "副科长", "处长", "副处长", "书记", "副书记",
    "领队", "教练", "裁判", "评委", "专家", "讲师", "主持人", "记录人",
    "工作人员", "参赛人员", "活动人员", "厂领导", "车间主任",
}

_PERSON_ROLE = (
    r"项目负责人|法定代表人|联系人|经办人|负责人|审核人|审批人|复核人|申请人|"
    r"填报人|制表人|签字人|承办人|主办人|验收人|组长|副组长|主任|副主任|"
    r"经理|副经理|部长|副部长|科长|副科长|处长|副处长|书记|副书记|领队|"
    r"教练|裁判|评委|专家|讲师|培训师|主持人|记录人|监考人|监督员|安全员|姓名"
)

_PERSON_LIST_LABEL = (
    r"参加活动人员|活动人员|参与人员|参加人员|参赛人员|培训人员|工作人员|"
    r"参会人员|人员名单|人员名册|联系人名单|经办人员|审核人员|审批人员|"
    r"项目成员|工作组成员|领导小组成员|筹备小组成员|小组成员|成员|组员|"
    r"评审专家|专家名单|评委名单"
)

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

_TOBACCO_ORG_ALIASES = (
    "中国烟草", "山东中烟", "云南中烟", "贵州中烟", "四川中烟", "重庆中烟", "湖南中烟",
    "湖北中烟", "河南中烟", "安徽中烟", "福建中烟", "广东中烟", "广西中烟", "陕西中烟",
    "甘肃烟草", "江苏中烟", "浙江中烟", "江西中烟", "河北中烟", "吉林烟草", "辽宁烟草",
    "黑龙江烟草", "内蒙古烟草", "上海烟草", "北京烟草", "天津烟草",
)
_TOBACCO_ORG_ALIAS_RE = "|".join(map(re.escape, sorted(_TOBACCO_ORG_ALIASES, key=len, reverse=True)))

_TOBACCO_LOCATIONS = (
    "云南", "山东", "贵州", "四川", "重庆", "河南", "湖南", "湖北", "福建", "广东", "广西",
    "陕西", "甘肃", "辽宁", "吉林", "黑龙江", "内蒙古", "新疆", "文山", "普洱", "曲靖", "保山",
    "大理", "德宏", "红河", "玉溪", "楚雄", "临沧", "昭通", "昆明", "丽江", "西双版纳",
)
_TOBACCO_LOCATION_ALT = "|".join(
    map(re.escape, sorted(_TOBACCO_LOCATIONS, key=len, reverse=True))
)
_TOBACCO_LOCATION_RE = re.compile(
    _TOBACCO_LOCATION_ALT
)
_LOCATION_CONTEXT_RE = re.compile(
    r"(?:产区|产地|地区|区域|来源地|来自|选自|分布于|覆盖)\s*(?:[：:]|为|是)?\s*"
    r"([^\n\r，,；;。]{2,160})"
)

_PRODUCT_STOPWORDS = {
    "产品", "品牌", "品名", "牌号", "规格", "型号", "模块", "原料", "烟叶", "卷烟", "配方",
    "主产品", "主要产品", "产品名称", "品牌名称", "模块名称", "典型产品", "典型模块组合",
}

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
        re.compile(rf"({_TOBACCO_ORG_ALIAS_RE})"),
        re.compile(rf"({_ORG_CHARS}{{2,70}}?(?:{_ORG_SUFFIX}))"),
    ],
    "person": [
        re.compile(
            rf"(?:{_PERSON_ROLE})\s*(?:[：:]|为|是)?\s*({_PERSON_NAME})"
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
    "product": [
        re.compile(
            r"(?:产品名称|品牌名称|模块名称|品名|牌号|品牌|产品|模块|原料)"
            r"\s*(?:[：:]|为|是)\s*([\u4e00-\u9fffA-Za-z0-9（）()·&＆+\-]{2,60})"
        ),
        re.compile(
            r"(?:型号|规格|配方编号|批次号)\s*(?:[：:]|为|是)?\s*"
            r"([A-Za-z0-9][A-Za-z0-9./_+\-]{1,39})"
        ),
    ],
    "location": [
        re.compile(rf"({_TOBACCO_LOCATION_ALT})(?=产区|产地|烟区)"),
    ],
}

_PERSON_LIST = re.compile(rf"(?:{_PERSON_LIST_LABEL})\s*[：:]\s*([^\n\r；;。]{{2,120}})")
_PERSON_WHOLE_RE = re.compile(rf"^{_PERSON_NAME}$")
_PERSON_LINE_RE = re.compile(rf"(?m)^[ \t]*({_PERSON_NAME})[ \t]*$")
_PERSON_LIST_ITEM_RE = re.compile(
    rf"^({_PERSON_NAME})(?:同志)?(?:[（(][^）)]{{1,20}}[）)])?(?:等\d*人)?$"
)
_FILENAME_PERSON_BOUNDARY_RE = re.compile(
    rf"(?:^|[_\-—\s、，,；;（）()【】])({_PERSON_NAME})"
    rf"(?=$|[_\-—\s、，,；;（）()【】]|同志)"
)
_FILENAME_DOCUMENT_WORDS = (
    r"(?:(?:个人|员工|职工|干部|岗位|年度|先进|优秀|获奖|培训|技能|劳动|活动|工作|项目|"
    r"竞赛|考核|任免|述职|履职|参赛|评选|报名|签到|成绩|事迹|信息)*)"
    r"(?:名单|名册|简历|履历|档案|方案|总结|报告|材料|通知|发言稿|申请表|审批表|"
    r"登记表|信息表|考核表|签到表|评分表|成绩表|合同|协议)"
)
_FILENAME_PERSON_TITLE_RE = re.compile(
    rf"(?:^|关于|表彰|推荐|任命|聘任|选派|申报|[_\-—\s、，,；;（）()【】])"
    rf"({_PERSON_NAME})(?:同志)?(?={_FILENAME_DOCUMENT_WORDS}(?:$|[_\-—\s、，,；;（）()【】]))"
)
_ORG_LEADING_NOISE = re.compile(
    r"^(?:(?:本项目|该项目|本合同|该合同|项目|合同|协议|我司|本公司|本单位|贵公司)?"
    r"(?:由|与|同|向|为|在|经|委托|交由)|"
    r"单位|机构|供应商|客户|甲方|乙方|采购人|招标人|中标人|承办单位|建设单位|"
    r"实施单位|所属单位|名称|全称)+\s*(?:[：:]|为|是)?\s*"
)

# Only derive abbreviations which preserve an organization's distinctive prefix
# and replace a well-known legal/industry suffix.  These values are candidates
# for human review, never silently trusted as entities or merged automatically.
_ORG_ABBREVIATION_SUFFIXES = (
    ("烟叶复烤厂", "厂"),
    ("复烤厂", "厂"),
    ("卷烟厂", "厂"),
    ("烟草专卖局", "烟草局"),
    ("有限责任公司", "公司"),
    ("股份有限公司", "公司"),
    ("集团有限公司", "集团"),
    ("集团公司", "集团"),
    ("有限公司", "公司"),
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
    if compact in _TOBACCO_LOCATIONS:
        return False
    return not re.search(
        r"(?:公司|集团|中心|单位|部门|项目|系统|地址|电话|人员|省|市|州|盟|区|县|旗|乡|镇|村|产区)$",
        compact,
    )


def _normalize_detected_value(value):
    return re.sub(r"\s+", " ", str(value or "")).strip(" ，,；;。.!！、/：:")


def _normalized_match_view(value):
    """Return a comparison view plus indexes back to the untouched source.

    Office XML, PDF extraction and OCR frequently represent the same visible
    value with full-width characters, zero-width controls or inserted spaces.
    Those differences must not decide whether an already confirmed entity is
    masked.  The index map lets callers replace only the original source span;
    surrounding wording and formatting are never regenerated.
    """
    normalized = []
    indexes = []
    for index, character in enumerate(str(value or "")):
        for output in unicodedata.normalize("NFKC", character):
            if output.isspace() or unicodedata.category(output) == "Cf":
                continue
            normalized.append(output.casefold())
            indexes.append(index)
    return "".join(normalized), indexes


def normalized_entity_key(value):
    return _normalized_match_view(value)[0]


def contains_equivalent(text, value):
    key = normalized_entity_key(value)
    return bool(key and key in normalized_entity_key(text))


def registered_match_spans(text, original_to_token):
    """Locate registered entities despite harmless extraction differences.

    Matches are longest-first and non-overlapping.  Each returned span points
    to the exact characters in ``text`` so callers can preserve all content
    outside the sensitive field.
    """
    source = str(text or "")
    view, indexes = _normalized_match_view(source)
    if not view or not indexes:
        return []
    by_key = {}
    for original, token in (original_to_token or {}).items():
        key = normalized_entity_key(original)
        if key and key not in by_key:
            by_key[key] = (original, token)
    candidates = []
    for key, (original, token) in sorted(by_key.items(), key=lambda item: len(item[0]), reverse=True):
        start_at = 0
        while True:
            start = view.find(key, start_at)
            if start < 0:
                break
            end = start + len(key)
            source_start = indexes[start]
            source_end = indexes[end - 1] + 1
            candidates.append({
                "start": source_start,
                "end": source_end,
                "text": source[source_start:source_end],
                "entity_text": original,
                "token": token,
                "normalized_length": len(key),
            })
            start_at = start + max(1, len(key))
    occupied = bytearray(len(source))
    selected = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-item["normalized_length"], item["start"], -(item["end"] - item["start"])),
    ):
        if occupied.find(1, candidate["start"], candidate["end"]) >= 0:
            continue
        occupied[candidate["start"]:candidate["end"]] = b"\x01" * (
            candidate["end"] - candidate["start"]
        )
        selected.append(candidate)
    return sorted(selected, key=lambda item: item["start"])


def _is_likely_product(value):
    compact = re.sub(r"\s+", "", value)
    if compact in _PRODUCT_STOPWORDS or not 2 <= len(compact) <= 60:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()·&＆+./_\-]{2,60}", compact))


def _is_likely_location(value):
    compact = re.sub(r"\s+", "", value)
    if compact in _TOBACCO_LOCATIONS:
        return True
    return bool(
        2 <= len(compact) <= 30
        and re.fullmatch(r"[\u4e00-\u9fff]{2,30}", compact)
        and re.search(r"(?:省|市|州|盟|区|县|旗|乡|镇|村|产区)$", compact)
    )


def _person_names_from_list(value):
    """Return complete list items only, avoiding role phrases that merely contain a surname."""
    for item in re.split(r"[、,，；;/\s]+|(?:以及|和|及)", value):
        item = item.strip(" ：:。.!！")
        if not item:
            continue
        match = _PERSON_LIST_ITEM_RE.fullmatch(item)
        if match and _is_likely_person_name(match.group(1)):
            yield match.group(1)


class MappingBuilder:
    def __init__(
        self,
        task_salt,
        enabled_categories=None,
        custom_entities=None,
        excluded_entities=None,
        previous_mapping=None,
        token_namespace="",
    ):
        self.task_salt = task_salt.upper()[:4]
        self.token_namespace = re.sub(r"[^A-Z0-9]", "", str(token_namespace or "").upper())[:10]
        self.enabled = tuple(dict.fromkeys(enabled_categories or DEFAULT_CATEGORIES))
        self.excluded_entities = {
            (normalized_entity_key(item.get("text")), item.get("category"))
            for item in (excluded_entities or [])
            if isinstance(item, dict) and normalized_entity_key(item.get("text"))
        }
        self.original_to_token = {}
        self.token_to_original = {}
        self.token_categories = {}
        self.alias_to_canonical = {}
        self.counters = Counter()
        self._previous_mapping = previous_mapping or {}
        self._historical_token_to_original = dict(self._previous_mapping.get("token_to_original", {}))
        self._historical_token_categories = dict(self._previous_mapping.get("token_categories", {}))
        self._restore_only_tokens = {}
        self._restore_only_categories = {}
        self._previous_tokens_by_key = {}
        self._used_tokens = set()
        previous_originals = self._previous_mapping.get("original_to_token") or {
            original: token
            for token, original in self._historical_token_to_original.items()
            if str(token).startswith("【")
        }
        for original, token in previous_originals.items():
            category = self._historical_token_categories.get(token, "custom")
            key = normalized_entity_key(original)
            if key:
                self._previous_tokens_by_key[(key, category)] = token
        for token, category in self._historical_token_categories.items():
            code = TOKEN_CODES.get(category, TOKEN_CODES["custom"])
            match = re.search(rf"{re.escape(code)}(\d+)】$", str(token))
            if match:
                self.counters[category] = max(self.counters[category], int(match.group(1)))
        for item in custom_entities or []:
            text = item.get("text", "").strip()
            category = item.get("category", "custom")
            if text:
                self.register(text, category if category in CATEGORY_LABELS else "custom")

    def register(self, original, category):
        original = original.strip()
        match_key = normalized_entity_key(original)
        existing = next((
            token for known, token in self.original_to_token.items()
            if normalized_entity_key(known) == match_key
        ), None)
        if (
            len(original) < 2
            or not match_key
            or "【" in original
            or (match_key, category) in self.excluded_entities
        ):
            return self.original_to_token.get(original)
        if existing:
            return existing
        # Overlapping values may be valid in different places (for example “文山” is
        # a production area while “文山雨露” is a product).  Replacement is applied
        # longest-first, so keeping both does not corrupt the longer value.
        previous_token = self._previous_tokens_by_key.get((match_key, category))
        if previous_token:
            token = previous_token
        else:
            self.counters[category] += 1
            code = TOKEN_CODES.get(category, TOKEN_CODES["custom"])
            prefix = f"{self.token_namespace}-" if self.token_namespace else ""
            token = f"【{prefix}{code}{self.counters[category]:03d}】"
        self._used_tokens.add(token)
        self.original_to_token[original] = token
        self.token_to_original[token] = original
        self.token_categories[token] = category
        return token

    def validate_detected(self, original, category):
        """Return a normalized model span only when its semantic type is plausible."""
        value = _normalize_detected_value(original)
        if category not in self.enabled or category not in DEFAULT_CATEGORIES:
            return None
        if category == "person":
            compact = value.replace(" ", "")
            if not _is_likely_person_name(compact):
                return None
            value = compact
        elif category == "organization":
            if not 2 <= len(value) <= 100:
                return None
        elif category == "address":
            if not 4 <= len(value) <= 120:
                return None
        elif category == "location":
            if not _is_likely_location(value):
                return None
        elif category == "product":
            if not _is_likely_product(value):
                return None
        if (normalized_entity_key(value), category) in self.excluded_entities:
            return None
        return value

    def register_detected(self, original, category):
        """Register a model-detected span after conservative type validation."""
        value = self.validate_detected(original, category)
        return self.register(value, category) if value else None

    def merge_aliases(self, canonical, aliases, category="organization"):
        """Make reviewed aliases share one reversible token.

        A shared token cannot preserve which surface form occurred at each
        position, so restoration deliberately uses ``canonical``.  The review
        API exposes this consequence before accepting a merge.
        """
        canonical = _normalize_detected_value(canonical)
        if not canonical or category not in CATEGORY_LABELS:
            return None
        canonical_token = self.original_to_token.get(canonical) or self.register(canonical, category)
        if not canonical_token:
            return None
        removed_tokens = set()
        for alias in aliases or []:
            alias = _normalize_detected_value(alias)
            if not alias or alias == canonical:
                continue
            old_token = self.original_to_token.get(alias)
            if not old_token:
                old_token = self.register(alias, category)
            if not old_token:
                continue
            if old_token != canonical_token:
                removed_tokens.add(old_token)
            self.original_to_token[alias] = canonical_token
            self.alias_to_canonical[alias] = canonical
        for token in removed_tokens:
            if token in self.token_to_original:
                self._restore_only_tokens[token] = self.token_to_original[token]
                self._restore_only_categories[token] = self.token_categories.get(token, category)
            self.token_categories.pop(token, None)
            self.token_to_original.pop(token, None)
            # Counters are monotonic identifiers. Decrementing here could make
            # a later entity reuse a number that another active token owns.
        self.token_to_original[canonical_token] = canonical
        self.token_categories[canonical_token] = category
        return canonical_token

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
                    for name in _person_names_from_list(list_match.group(1)):
                        name_start = list_match.group(1).find(name)
                        start_in_view = list_match.start(1) + name_start
                        end_in_view = start_in_view + len(name)
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

            if "location" in self.enabled:
                for context_match in _LOCATION_CONTEXT_RE.finditer(view):
                    context_value = context_match.group(1)
                    for location_match in _TOBACCO_LOCATION_RE.finditer(context_value):
                        start_in_view = context_match.start(1) + location_match.start()
                        end_in_view = context_match.start(1) + location_match.end()
                        span = _source_span(text, indexes, start_in_view, end_in_view)
                        if span:
                            key = (span[0], span[1], "location", span[2])
                            if key not in seen:
                                seen.add(key)
                                candidates.append(key)

        stripped = text.strip()
        if "person" in self.enabled:
            if _is_likely_person_name(stripped):
                start = text.find(stripped)
                candidates.append((start, start + len(stripped), "person", stripped))
        if "location" in self.enabled and stripped in _TOBACCO_LOCATIONS:
            start = text.find(stripped)
            candidates.append((start, start + len(stripped), "location", stripped))
        return candidates

    def discover(self, text):
        candidates = self._pattern_candidates(text)
        # Prefer the longest candidate when rules overlap (for example a full tobacco
        # company name that also contains a shorter generic “company” match).
        selected = []
        occupied = bytearray(len(text))
        for start, end, category, value in sorted(
            candidates, key=lambda item: (-(item[1] - item[0]), item[0], DEFAULT_CATEGORIES.index(item[2]))
        ):
            if occupied.find(1, start, end) >= 0:
                continue
            selected.append((start, category, value))
            occupied[start:end] = b"\x01" * (end - start)
        for _, category, value in sorted(selected, key=lambda item: item[0]):
            self.register(value, category)

    def _replace_registered(self, text, filename=False):
        matches = registered_match_spans(text, self.original_to_token)
        if not matches:
            return text
        result = text
        for match in reversed(matches):
            original = match["entity_text"]
            content_token = match["token"]
            if not filename:
                replacement = content_token
            else:
                replacement = f"ANON_{content_token[1:-1]}"
                self.token_to_original[replacement] = self.token_to_original.get(content_token, original)
                self.token_categories[replacement] = self.token_categories[content_token]
            result = result[:match["start"]] + replacement + result[match["end"]:]
        return result

    def anonymize(self, text):
        if not text:
            return text
        self.discover(text)
        return self._replace_registered(text)

    def anonymize_registered(self, text):
        """Replace only the mapping built during the discovery phase.

        File processing first extracts and discovers every text section.  The
        write phase must not run all recognition patterns again for every XML
        node or spreadsheet cell.
        """
        if not text:
            return text
        return self._replace_registered(text)

    def anonymize_filename_stem(self, stem):
        """Anonymize a filename stem while reusing the document's reversible mapping."""
        if not stem:
            return stem
        self.discover(stem)
        if "person" in self.enabled:
            for pattern in (_FILENAME_PERSON_BOUNDARY_RE, _FILENAME_PERSON_TITLE_RE):
                for match in pattern.finditer(stem):
                    value = match.group(1)
                    if _is_likely_person_name(value):
                        self.register(value, "person")
        return self._replace_registered(stem, filename=True)

    def export(self):
        token_to_original = dict(self._historical_token_to_original)
        token_to_original.update(self._restore_only_tokens)
        token_to_original.update(self.token_to_original)
        token_categories = dict(self._historical_token_categories)
        token_categories.update(self._restore_only_categories)
        token_categories.update(self.token_categories)
        return {
            "version": 4,
            "namespace": self.token_namespace,
            "token_to_original": token_to_original,
            "token_categories": token_categories,
            "original_to_token": self.original_to_token,
            "alias_to_canonical": self.alias_to_canonical,
            "active_tokens": sorted(set(self.original_to_token.values())),
        }

    def counts(self):
        active = Counter(self.token_categories.get(token, "custom") for token in set(self.original_to_token.values()))
        return {CATEGORY_LABELS.get(key, key): value for key, value in active.items()}


def build_restorer(mapping):
    replacements = mapping.get("token_to_original", {})
    if not replacements:
        return lambda text: text
    pattern = re.compile("|".join(re.escape(token) for token in sorted(replacements, key=len, reverse=True)))

    def restore(text):
        if not text:
            return text
        return pattern.sub(lambda match: replacements[match.group(0)], text)

    return restore


def restore_text(text, mapping):
    return build_restorer(mapping)(text)


def suggest_organization_alias_groups(builder, text):
    """Register and return conservative full-name/abbreviation suggestions.

    Suggestions are limited to derived abbreviations that actually occur in
    the same document.  Human review decides whether the abbreviation is an
    entity and whether it shares the full name's token.
    """
    if "organization" not in builder.enabled or not text:
        return []
    organizations = []
    for original, token in list(builder.original_to_token.items()):
        if builder.token_categories.get(token) == "organization":
            organizations.append(original)
    groups = []
    seen_pairs = set()
    for full_name in sorted(organizations, key=len, reverse=True):
        for suffix, short_suffix in _ORG_ABBREVIATION_SUFFIXES:
            if not full_name.endswith(suffix):
                continue
            prefix = full_name[:-len(suffix)].strip()
            alias = f"{prefix}{short_suffix}"
            if len(prefix) < 2 or alias == full_name or alias not in text:
                continue
            pair = (full_name, alias)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            token = builder.register(alias, "organization")
            if not token:
                continue
            groups.append({
                "id": f"organization-{len(groups) + 1}",
                "category": "organization",
                "canonical": full_name,
                "members": [full_name, alias],
                "reason": f"“{alias}”与“{full_name}”具有相同主体词和单位后缀",
                "confidence": 0.92,
                "accepted": False,
            })
    return groups
