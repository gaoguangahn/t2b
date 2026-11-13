"""复制此方法到已有 AdbFunctionMixin，替换原 get_page_elements 即可。

self.device 仍是原来的 uiautomator2 设备对象；返回值仍是控件列表。
无需命令行入口、设备重连或文件输出。
"""
import uiautomator2 as u2

def get_page_elements(device, light: bool = False) -> list[dict]:
    """采集当前页面，保留text/desc/resourceId至少一个非空的节点。

    light只保留为旧调用的兼容参数；True/False均返回下列相同字段，
    不再因light=True丢弃resourceId或仅有ID的控件。
    bounds保留原方法的设备像素字符串格式，node_path为本次XML内过滤前的0基路径，
    仅表示现场层级，不作为稳定脚本定位。缺失状态为None，不默认False。
    """
    import xml.etree.ElementTree as ET

    current_page = device.dump_hierarchy(compressed=True)
    if not current_page:
        return []

    def read_bool(node, name):
        value = node.get(name)
        return {"true": True, "false": False}.get(value.strip().lower()) if value is not None else None

    root = ET.fromstring(current_page)
    roots = [root] if root.tag == "node" else list(root.findall("node"))
    pending = [(node, [index]) for index, node in reversed(list(enumerate(roots)))]
    elements = []
    while pending:
        node, path = pending.pop()
        # 先生成原树路径，再过滤；被删除的容器和兄弟节点不会改变路径。
        children = list(node.findall("node"))
        pending.extend((child, [*path, index]) for index, child in reversed(list(enumerate(children))))

        text = node.get("text", "")
        desc = node.get("content-desc", "")
        resource_id = node.get("resource-id", "")
        if not any(value.strip() for value in (text, desc, resource_id)):
            continue

        elements.append({
            "text": text,
            "desc": desc,
            "resourceId": resource_id,
            "bounds": node.get("bounds", ""),
            "className": node.get("class") or None,
            "clickable": read_bool(node, "clickable"),
            "checkable": read_bool(node, "checkable"),
            "checked": read_bool(node, "checked"),
            "selected": read_bool(node, "selected"),
            "enabled": read_bool(node, "enabled"),
            "node_path": path,
        })
    return elements



if __name__ == '__main__':
    d = u2.connect()
    elements = get_page_elements(device=d)
    print(elements)