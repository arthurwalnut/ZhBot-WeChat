"""UIA locating rules only. No inferred WeChat identity or version support."""

# Observed on this computer, 2026-10-25. Message controls were not exposed in
# the empty chat page; leave their selectors empty until a real session is read.
PROCESS_NAMES = {"weixin.exe", "wechat.exe"}
SELECTOR_FIELDS = ("control_type", "class_name", "automation_id", "name")


def matches(element, selector):
    return bool(selector) and all(
        getattr(element, key) == value for key, value in selector.items()
        if key in SELECTOR_FIELDS
    ) and all(key in SELECTOR_FIELDS for key in selector)


def unique(elements, selector, label):
    if not selector:
        raise ValueError(f"{label}尚未配置；请先在真实会话检查 UIA 控件并填写规则。")
    found = [element for element in elements if matches(element, selector)]
    if len(found) != 1:
        raise ValueError(f"{label}应唯一匹配，实际 {len(found)} 个；暂停并重新选择。")
    return found[0]
