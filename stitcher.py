"""图片拼接核心逻辑（纯函数，便于无头测试与复用）。

支持的选项：
- direction: "horizontal"（横向，图片从左到右排）| "vertical"（纵向，图片从上到下排）
- align: "start" | "center" | "end"
    * 横向拼接时控制垂直方向对齐：上对齐 / 居中 / 下对齐
    * 纵向拼接时控制水平方向对齐：左对齐 / 居中 / 右对齐
- scale_mode: "none"（保持原图尺寸）| "unify"（统一堆叠维度的尺寸后再拼）
    * 横向拼接 -> 统一高度（以最大高度为基准，等比缩放）
    * 纵向拼接 -> 统一宽度（以最大宽度为基准，等比缩放）
- gap: 图片之间的间隙像素（>=0）
- bg: 背景色，格式 (R, G, B) 或 (R, G, B, A)
"""

from __future__ import annotations

from PIL import Image

# 对齐方式常量
ALIGN_START = "start"
ALIGN_CENTER = "center"
ALIGN_END = "end"

# 缩放模式常量
SCALE_NONE = "none"
SCALE_UNIFY = "unify"


def _parse_bg(bg) -> tuple:
    """把背景色规范化为 (R, G, B, A)。"""
    if bg is None:
        return (255, 255, 255, 255)
    if len(bg) == 3:
        return (int(bg[0]), int(bg[1]), int(bg[2]), 255)
    if len(bg) == 4:
        return (int(bg[0]), int(bg[1]), int(bg[2]), int(bg[3]))
    raise ValueError(f"无效的背景色: {bg}")


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def _normalize(img: Image.Image) -> Image.Image:
    """统一转成 RGBA，方便合成与透明处理。"""
    if img.mode == "P" and "transparency" in img.info:
        return img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        return img.convert("RGBA")
    if img.mode == "L":
        return img.convert("RGBA")
    return img.convert("RGB")


def _scale_to(img: Image.Image, target: int, axis: str) -> Image.Image:
    """按 axis='h' 统一高度，或 axis='w' 统一宽度，等比缩放。"""
    w, h = img.size
    if axis == "h":
        if h == target:
            return img
        new_w = max(1, round(w * target / h))
        return img.resize((new_w, target), Image.LANCZOS)
    else:  # axis == "w"
        if w == target:
            return img
        new_h = max(1, round(h * target / w))
        return img.resize((target, new_h), Image.LANCZOS)


def stitch(
    images,
    direction: str = "horizontal",
    align: str = "center",
    scale_mode: str = "none",
    gap: int = 0,
    bg=(255, 255, 255, 255),
):
    """把多张图片拼接成一张。

    :param images: 可迭代的 PIL.Image.Image（调用方负责打开/关闭）
    :return: 拼接后的 PIL.Image.Image（RGBA 或 RGB，取决于背景是否透明）
    """
    if not images:
        raise ValueError("至少需要一张图片")

    imgs = [_normalize(im) for im in images]
    n = len(imgs)
    bg = _parse_bg(bg)

    # 1) 缩放：统一堆叠维度的尺寸
    if scale_mode == SCALE_UNIFY:
        if direction == "horizontal":
            target = max(im.height for im in imgs)
            imgs = [_scale_to(im, target, "h") for im in imgs]
        else:
            target = max(im.width for im in imgs)
            imgs = [_scale_to(im, target, "w") for im in imgs]

    # 记录是否有透明通道（用于决定输出模式）
    any_alpha = any(_has_alpha(im) for im in imgs)

    # 2) 计算画布尺寸
    if direction == "horizontal":
        total_w = sum(im.width for im in imgs) + gap * (n - 1)
        total_h = max(im.height for im in imgs)
    else:
        total_w = max(im.width for im in imgs)
        total_h = sum(im.height for im in imgs) + gap * (n - 1)

    # 3) 创建画布（统一用 RGBA 内部合成，最后再按需转 RGB）
    transparent_canvas = (bg[3] < 255) or any_alpha
    canvas = Image.new("RGBA", (total_w, total_h), bg if transparent_canvas else (0, 0, 0, 0))

    # 4) 逐张贴图：先放进一张同样大小的透明图层，再用 alpha_composite 合成
    if direction == "horizontal":
        x = 0
        for im in imgs:
            if align == ALIGN_START:
                y = 0
            elif align == ALIGN_END:
                y = total_h - im.height
            else:  # center
                y = (total_h - im.height) // 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer.paste(im, (x, y))
            canvas = Image.alpha_composite(canvas, layer)
            x += im.width + gap
    else:
        y = 0
        for im in imgs:
            if align == ALIGN_START:
                x = 0
            elif align == ALIGN_END:
                x = total_w - im.width
            else:  # center
                x = (total_w - im.width) // 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer.paste(im, (x, y))
            canvas = Image.alpha_composite(canvas, layer)
            y += im.height + gap

    # 5) 无需透明时转回 RGB（更紧凑，且 JPG 友好）
    if not transparent_canvas:
        canvas = canvas.convert("RGB")

    return canvas


def save_result(img: Image.Image, out_path: str):
    """根据扩展名自动选择保存格式；JPG 自动转 RGB 并铺白底。"""
    ext = out_path.rsplit(".", 1)[-1].lower() if "." in out_path else "png"
    if ext in ("jpg", "jpeg"):
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        else:
            img = img.convert("RGB")
        img.save(out_path, "JPEG", quality=92)
    elif ext == "webp":
        img.save(out_path, "WEBP")
    else:  # png
        img.save(out_path, "PNG")
