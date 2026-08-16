"""Shared entity schema for UIE inference and training dataset export.

Keeping the runtime prompts and exported training prompts in one module avoids
silently producing a dataset that cannot be used to fine-tune the deployed
model.
"""

UIE_SCHEMA_BY_CATEGORY = {
    "person": ["人名"],
    "organization": ["单位名称", "部门名称"],
    "address": ["详细地址"],
    "location": ["烟叶产区"],
    "product": ["烟草品牌或产品名称"],
}

UIE_SCHEMA_CATEGORY = {
    prompt: category
    for category, prompts in UIE_SCHEMA_BY_CATEGORY.items()
    for prompt in prompts
}

# Human annotations currently distinguish the business category but not the
# organization subtype (unit vs department). Export one unambiguous canonical
# prompt per category; do not create false negative "部门名称" samples.
UIE_TRAINING_PROMPT_BY_CATEGORY = {
    "person": "人名",
    "organization": "单位名称",
    "address": "详细地址",
    "location": "烟叶产区",
    "product": "烟草品牌或产品名称",
}
