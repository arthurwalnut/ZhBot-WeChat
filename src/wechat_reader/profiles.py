"""UIA locating rules only. No inferred WeChat identity or version support."""

# Observed on WeChat 4.1.15.13, 2026-10-29. Capability checks also run on
# later versions; a matching version number alone is not a compatibility claim.
PROCESS_NAMES = {"weixin.exe", "wechat.exe"}
SELECTOR_FIELDS = ("control_type", "class_name", "automation_id", "name")
TITLE_ID = ("content_view.top_content_view.title_h_view.left_v_view."
            "left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label")
MMUI_SELECTORS = {
    "title": {"control_type": "Text", "automation_id": TITLE_ID},
    "messages": {"control_type": "List", "class_name": "mmui::RecyclerListView",
                 "automation_id": "chat_message_list"},
    "row": {"control_type": "ListItem"},
    "text": {"control_type": "ListItem", "class_name": "mmui::ChatTextItemView"},
}


def detect_chat_type(nodes):
    if any(n.class_name == "mmui::ChatTitleBarChatSingleView" for n in nodes):
        return "private"
    return None


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
