"""图片横向/纵向拼接小工具 - 图形界面（tkinter）。

运行方式（在项目目录下）：
    uv run python app.py
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import time
import tkinter as tk
from urllib.parse import unquote, urlparse
from tkinter import filedialog, colorchooser, messagebox, ttk
from PIL import Image, ImageGrab, ImageOps, ImageTk

import stitcher

try:
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
    _DND_AVAILABLE = True
except Exception:  # 未安装 tkinterdnd2：功能自动降级为普通 Tk，拖拽停用
    _DND_AVAILABLE = False

_DND_ACTIVE = False
_DND_INIT_ERROR = ""

# 对齐方式内部值
ALIGN_VALUES = ("start", "center", "end")

# 支持导入的图片扩展名（文件对话框 / 拖拽 / 剪贴板文件列表共用）
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tiff", ".tif", ".ico"}


def reorder_block(items: list, sel: list[int], target: int, direction: int) -> tuple[list, list[int]]:
    """列表内拖拽排序的核心重排：把 sel 索引的元素作为整块移动。

    direction > 0（往下拖）放到 target 行之后，< 0（往上拖）放到 target 行之前；
    返回 (新列表, 新选中索引列表)，块内原有顺序保持不变。
    """
    s = sorted(sel)
    sset = set(s)
    block = [items[i] for i in s]
    rest = [it for i, it in enumerate(items) if i not in sset]
    pos = target - sum(1 for i in s if i < target)  # target 行在 rest 里的下标
    insert_at = pos + 1 if direction > 0 else pos
    new_items = rest[:insert_at] + block + rest[insert_at:]
    new_sel = list(range(insert_at, insert_at + len(block)))
    return new_items, new_sel

ASSET_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_PATH = os.path.join(ASSET_DIR, "app.ico")


def apply_app_icon(root: tk.Tk):
    """设置窗口图标（assets/app.ico），兼容源码运行与 PyInstaller 打包。"""
    if not os.path.exists(ICON_PATH):
        return
    try:
        root.iconbitmap(ICON_PATH)  # Windows：标题栏 + 任务栏
    except tk.TclError:
        try:
            root.iconphoto(True, ImageTk.PhotoImage(Image.open(ICON_PATH)))
        except Exception:
            pass


# ---------------- 剪贴板（Windows CF_DIB 写入） ----------------
def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """任意模式 → RGB（透明区域铺白底，剪贴板 DIB 不支持 alpha）。"""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    if img.mode == "P":
        return _flatten_to_rgb(img.convert("RGBA"))
    return img.convert("RGB")


def image_to_dib(img: Image.Image) -> bytes:
    """PIL Image → 24bit DIB（BITMAPINFOHEADER + 自底向上 BGR 像素，行按 4 字节对齐）。"""
    rgb = _flatten_to_rgb(img)
    w, h = rgb.size
    row_size = (w * 3 + 3) & ~3
    # BITMAPINFOHEADER: 长度40 / 宽 / 高(正=自底向上) / 1平面 / 24bpp / 不压缩 / 数据大小 / 其余0
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, row_size * h, 0, 0, 0, 0)
    flipped = rgb.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    raw = flipped.tobytes("raw", "BGR")
    pad = row_size - w * 3
    if pad:
        lines = [raw[y * w * 3:(y + 1) * w * 3] + b"\x00" * pad for y in range(h)]
        raw = b"".join(lines)
    return header + raw


def copy_image_to_clipboard(img: Image.Image) -> bool:
    """把 PIL Image 以 CF_DIB 写入 Windows 剪贴板（微信/QQ/画图/Word 均可直接粘贴）。"""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    CF_DIB, GMEM_MOVEABLE = 8, 0x0002
    dib = image_to_dib(img)

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k32.GlobalFree.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]

    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not h:
            return False
        p = k32.GlobalLock(h)
        if not p:
            k32.GlobalFree(h)
            return False
        ctypes.memmove(p, dib, len(dib))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_DIB, h):
            k32.GlobalFree(h)  # 设置失败时句柄仍归我们，需自己释放
            return False
        return True  # 成功后句柄归剪贴板系统所有，不能释放
    finally:
        u32.CloseClipboard()


class StitcherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("图片拼接小工具")
        root.geometry("800x620")
        root.resizable(True, True)
        apply_app_icon(root)

        self.paths: list[str] = []          # 已选图片路径
        self.rotations: list[int] = []      # 每张图的手动旋转角（0/90/180/270，逆时针为正）
        self.bg_color = (255, 255, 255)      # 背景色 RGB
        self.transparent = tk.BooleanVar(value=False)  # 是否透明背景
        self._photo = None                   # 预览缩略图引用（防被 GC 回收）
        self._result_img = None             # 最近一次拼接的完整结果图（右键复制用）
        self._preview_job = None            # 防抖中的自动预览任务 id
        self._drag: dict | None = None      # 列表内拖拽排序的进行中状态
        self._thumbs: dict = {}             # 列表缩略图缓存，key=(路径, 旋转角)

        self._build_ui()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        # 顶部：方向 + 对齐 + 缩放
        opt_frame = ttk.LabelFrame(self.root, text="拼接选项", padding=8)
        opt_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=8)
        opt_frame.columnconfigure(1, weight=1)
        opt_frame.columnconfigure(3, weight=1)

        ttk.Label(opt_frame, text="方向：").grid(row=0, column=0, sticky="w")
        self.direction = tk.StringVar(value="vertical")
        ttk.Radiobutton(opt_frame, text="横向（左右排）", variable=self.direction,
                        value="horizontal", command=self._on_direction_change).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opt_frame, text="纵向（上下排）", variable=self.direction,
                        value="vertical", command=self._on_direction_change).grid(row=0, column=2, sticky="w")

        ttk.Label(opt_frame, text="对齐：").grid(row=1, column=0, sticky="w")
        self.align = tk.StringVar(value="center")
        self.align_rb = {}
        for i, v in enumerate(ALIGN_VALUES):
            rb = ttk.Radiobutton(opt_frame, text="", variable=self.align, value=v)
            rb.grid(row=1, column=1 + i, sticky="w")
            self.align_rb[v] = rb

        ttk.Label(opt_frame, text="缩放：").grid(row=2, column=0, sticky="w")
        self.scale_mode = tk.StringVar(value="unify")
        ttk.Radiobutton(opt_frame, text="不缩放（按原图）", variable=self.scale_mode,
                        value="none").grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(opt_frame, text="统一尺寸后拼接", variable=self.scale_mode,
                        value="unify").grid(row=2, column=2, sticky="w")

        ttk.Label(opt_frame, text="间隙(px)：").grid(row=3, column=0, sticky="w")
        self.gap = tk.IntVar(value=0)
        ttk.Spinbox(opt_frame, from_=0, to=200, width=8, textvariable=self.gap).grid(row=3, column=1, sticky="w")

        ttk.Label(opt_frame, text="背景：").grid(row=3, column=2, sticky="w")
        self.bg_btn = ttk.Button(opt_frame, text="选择颜色", command=self._choose_color)
        self.bg_btn.grid(row=3, column=3, sticky="w")
        self.bg_preview = tk.Label(opt_frame, width=4, relief="sunken", bg="#ffffff")
        self.bg_preview.grid(row=3, column=4, padx=4)
        ttk.Checkbutton(opt_frame, text="透明背景", variable=self.transparent,
                        command=self._update_bg_preview).grid(row=3, column=5, sticky="w")

        self._on_direction_change()  # 初始化对齐文字

        # 左侧：图片列表
        list_frame = ttk.LabelFrame(self.root, text="图片列表（可拖入文件 / 拖拽排序 / Ctrl+V 粘贴，▲▼ 微调）", padding=8)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        # 行高按缩略图尺寸加大（Treeview 才支持条目内图片，Listbox 不支持）
        self._style = ttk.Style(self.root)
        self._style.configure("Thumb.Treeview", rowheight=40)
        self.tree = ttk.Treeview(list_frame, style="Thumb.Treeview", show="tree",
                                 selectmode="extended", height=10)
        self.tree.grid(row=0, column=0, columnspan=8, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=8, sticky="ns")
        self.tree.config(yscrollcommand=sb.set)

        # 列表内拖拽排序（纯 tkinter 实现，多选时整块拖动）
        self.tree.bind("<ButtonPress-1>", self._on_drag_press)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)

        btn_row1 = 1
        btn_row2 = 2
        ttk.Button(list_frame, text="添加图片", command=self._add_images).grid(row=btn_row1, column=0, padx=2, pady=4)
        ttk.Button(list_frame, text="移除", command=self._remove).grid(row=btn_row1, column=1, padx=2, pady=4)
        ttk.Button(list_frame, text="上移 ▲", command=lambda: self._move(-1)).grid(row=btn_row1, column=2, padx=2, pady=4)
        ttk.Button(list_frame, text="左转90°", command=lambda: self._rotate(90)).grid(row=btn_row1, column=3, padx=2, pady=4)
        ttk.Button(list_frame, text="粘贴", command=self._paste_from_clipboard).grid(row=btn_row2, column=0, padx=2, pady=4)
        ttk.Button(list_frame, text="清空", command=self._clear).grid(row=btn_row2, column=1, padx=2, pady=4)
        ttk.Button(list_frame, text="下移 ▼", command=lambda: self._move(1)).grid(row=btn_row2, column=2, padx=2, pady=4)
        ttk.Button(list_frame, text="右转90°", command=lambda: self._rotate(-90)).grid(row=btn_row2, column=3, padx=2, pady=4)

        # 右侧：预览
        prev_frame = ttk.LabelFrame(self.root, text="预览", padding=8)
        prev_frame.grid(row=1, column=1, sticky="nsew", padx=10, pady=(0, 8))
        prev_frame.rowconfigure(0, weight=1)
        prev_frame.columnconfigure(0, weight=1)
        self.preview_label = ttk.Label(prev_frame, text="（尚未拼接）", anchor="center", relief="sunken")
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        self.size_label = ttk.Label(prev_frame, text="结果尺寸：—")
        self.size_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(prev_frame, text="刷新预览", command=self._preview).grid(row=2, column=0, pady=6)

        # 预览图右键菜单：复制拼接结果到剪贴板
        self._preview_menu = tk.Menu(self.preview_label, tearoff=0)
        self._preview_menu.add_command(label="复制", command=self._copy_from_preview)
        self.preview_label.bind("<Button-3>", self._on_preview_right_click)

        # 底部：操作
        action_frame = ttk.Frame(self.root, padding=8)
        action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(action_frame, text="退出", command=self.root.destroy).pack(side="right")
        ttk.Button(action_frame, text="拼接并保存", command=self._save).pack(side="right", padx=6)
        ttk.Button(action_frame, text="复制到剪贴板", command=self._copy_clipboard).pack(side="right", padx=6)

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        # 选项变化 → 自动刷新预览（防抖见 _schedule_preview）
        for var in (self.direction, self.align, self.scale_mode, self.gap, self.transparent):
            var.trace_add("write", lambda *_: self._schedule_preview())

        # 剪贴板粘贴 + 拖拽导入
        self.root.bind("<Control-v>", self._on_ctrl_v)
        self.root.bind("<Control-V>", self._on_ctrl_v)
        self._setup_dnd()

    # ---------------- 事件处理 ----------------
    def _on_direction_change(self):
        if self.direction.get() == "horizontal":
            labels = {"start": "上对齐", "center": "垂直居中", "end": "下对齐"}
        else:
            labels = {"start": "左对齐", "center": "水平居中", "end": "右对齐"}
        for v in ALIGN_VALUES:
            self.align_rb[v].config(text=labels[v])

    def _choose_color(self):
        if self.transparent.get():
            messagebox.showinfo("提示", "当前已选择透明背景，先取消“透明背景”再选颜色。")
            return
        rgb, hexcolor = colorchooser.askcolor(color="#%02x%02x%02x" % self.bg_color)
        if rgb:
            self.bg_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            self._update_bg_preview()

    def _update_bg_preview(self):
        if self.transparent.get():
            self.bg_preview.config(bg="#aaaaaa")
            self.bg_preview.config(text="透明", fg="white")
        else:
            hexc = "#%02x%02x%02x" % self.bg_color
            self.bg_preview.config(bg=hexc, text="")
        self._schedule_preview()  # 背景色/透明切换也触发自动预览

    def _add_images(self):
        files = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tiff")]
        )
        self._add_paths(files)

    def _add_paths(self, paths) -> int:
        """把一组路径加入图片列表（按扩展名过滤、自动去重、目录则展开其中的图片）。

        供文件对话框 / 拖拽 / 剪贴板文件列表共用。返回实际新增数量。
        """
        new = []
        for f in paths:
            f = str(f)
            if os.path.isdir(f):
                try:
                    for name in sorted(os.listdir(f)):
                        q = os.path.join(f, name)
                        if os.path.isfile(q) and os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                            new.append(q)
                except OSError:
                    pass
            elif os.path.isfile(f) and os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                new.append(f)
        added = 0
        for f in new:
            if f not in self.paths:
                self.paths.append(f)
                added += 1
        if added:
            self._refresh_list()
        return added

    # ---------------- 剪贴板 ----------------
    def _on_ctrl_v(self, event):
        # 焦点在输入框（间隙 Spinbox 等）时不抢按键，让系统正常粘贴文本
        w = self.root.focus_get()
        if w is not None and w.winfo_class() in ("Entry", "TEntry", "Spinbox", "TSpinbox", "Text"):
            return
        self._paste_from_clipboard()

    def _paste_from_clipboard(self, event=None):
        """从剪贴板导入图片：支持位图（截图/复制自图片查看器）和复制的图片文件列表。"""
        try:
            data = ImageGrab.grabclipboard()
        except Exception as e:
            messagebox.showerror("粘贴失败", str(e))
            return
        if data is None:
            messagebox.showinfo("粘贴", "剪贴板中没有图片。")
            return
        if isinstance(data, Image.Image):
            # 位图内容：先落到临时目录，再进入列表管线
            d = os.path.join(tempfile.gettempdir(), "ImageStitcher_paste")
            os.makedirs(d, exist_ok=True)
            base = os.path.join(d, time.strftime("paste_%Y%m%d_%H%M%S"))
            p = base + ".png"
            i = 1
            while os.path.exists(p):  # 同秒多次粘贴避免覆盖
                p = f"{base}_{i}.png"
                i += 1
            data.save(p)
            files = [p]
        else:
            files = list(data)
        n = self._add_paths(files)
        if n == 0:
            messagebox.showinfo("粘贴", "剪贴板中没有可用的图片文件。")

    def _on_preview_right_click(self, event):
        """预览图区域右键弹出菜单。"""
        self._preview_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _copy_from_preview(self):
        """把预览中显示的拼接结果复制到剪贴板（右键“复制”入口）。"""
        if self._result_img is None:
            messagebox.showwarning("提示", "请先拼接出预览图。")
            return
        try:
            if copy_image_to_clipboard(self._result_img):
                messagebox.showinfo(
                    "完成", f"已复制到剪贴板（可直接 Ctrl+V 粘贴）。\n尺寸：{self._result_img.size[0]} × {self._result_img.size[1]}"
                )
            else:
                messagebox.showerror("复制失败", "当前平台不支持把图片写入剪贴板。")
        except Exception as e:
            messagebox.showerror("复制失败", str(e))

    def _copy_clipboard(self):
        """拼接当前列表并复制结果到剪贴板。"""
        if not self.paths:
            messagebox.showwarning("提示", "请先添加图片。")
            return
        try:
            imgs = self._open_images()
            try:
                out = self._do_stitch(imgs)
            finally:
                for im in imgs:
                    im.close()
            if copy_image_to_clipboard(out):
                messagebox.showinfo(
                    "完成", f"已复制到剪贴板（可直接 Ctrl+V 粘贴）。\n尺寸：{out.size[0]} × {out.size[1]}"
                )
            else:
                messagebox.showerror("复制失败", "当前平台不支持把图片写入剪贴板。")
        except Exception as e:
            messagebox.showerror("复制失败", str(e))

    # ---------------- 拖拽导入 ----------------
    def _setup_dnd(self):
        """注册文件和文本拖拽目标：列表框 + 整个窗口。"""
        self._dnd_registered = False
        if not _DND_AVAILABLE or not hasattr(self.root, "drop_target_register"):
            return
        try:
            for w in (self.root, self.tree):
                w.drop_target_register(DND_FILES, DND_TEXT)
                w.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                w.dnd_bind("<<DropLeave>>", self._on_drop_leave)
                w.dnd_bind("<<Drop>>", self._on_drop)
            self._dnd_registered = True
        except Exception as e:
            self._dnd_register_error = f"{type(e).__name__}: {e}"

    def _on_drop_enter(self, event):
        self._drop_prev_status = self.size_label.cget("text")
        self.tree.config(cursor="plus")  # 悬停提示：松手放这里（ttk 控件不能直接改 bg）
        self.size_label.config(text="松开鼠标即可添加图片…")
        return "copy"

    def _on_drop_leave(self, event):
        self.tree.config(cursor="")
        previous = getattr(self, "_drop_prev_status", "结果尺寸：—")
        if self.size_label.cget("text") == "松开鼠标即可添加图片…":
            self.size_label.config(text=previous)

    def _parse_drop_paths(self, data):
        """兼容 DND_FILES Tcl 列表、普通路径和 file:// URI。"""
        if isinstance(data, (tuple, list)):
            items = [str(x) for x in data]
        else:
            text = str(data).strip()
            if not text:
                return []
            if os.path.exists(text):
                items = [text]
            elif "\n" in text or "\r" in text:
                items = [line.strip() for line in text.splitlines() if line.strip()]
            else:
                try:
                    items = list(self.root.tk.splitlist(text))
                except Exception:
                    items = [text]
        paths = []
        for item in items:
            item = item.strip().strip('"')
            parsed = urlparse(item)
            if parsed.scheme.lower() == "file":
                item = unquote(parsed.path)
                if len(item) >= 3 and item[0] == "/" and item[2] == ":":
                    item = item[1:]  # file:///C:/... → C:/...
                if parsed.netloc:
                    item = f"//{parsed.netloc}{item}"
            paths.append(item)
        return paths

    def _on_drop(self, event):
        self._on_drop_leave(event)
        try:
            paths = self._parse_drop_paths(event.data)
            n = self._add_paths(paths)
            self.size_label.config(
                text=f"已添加 {n} 张图片" if n else "未识别到图片文件（支持 PNG/JPG/WebP 等）"
            )
        except Exception as e:
            self.size_label.config(text=f"拖入失败：{str(e)[:80]}")

    def _remove(self):
        sel = self._sel_indices()
        for i in reversed(sel):
            self.paths.pop(i)
        self._refresh_list()

    # ---------------- 列表内拖拽排序 ----------------
    def _on_drag_press(self, e):
        if not self.paths:
            return
        if e.state & 0x0005:  # Shift/Ctrl 组合键：交给默认的多选逻辑，不发起拖拽
            self._drag = None
            return
        row = self.tree.identify_row(e.y)
        if not row:
            return
        i = self.tree.index(row)
        sel = self._sel_indices()
        if i not in sel:  # 按在未选中行上 → 单选该行再拖
            self.tree.selection_set(row)
            sel = [i]
        self._drag = {"sel": sel, "last": i}
        self.tree.config(cursor="fleur")
        if len(sel) > 1:
            return "break"  # 按住已选中的多选块：保持整块选中，不让默认行为收成单选

    def _on_drag_motion(self, e):
        st = self._drag
        if not st or not self.paths:
            return
        # 拖到列表上下边缘时按条目占比滚动
        h = self.tree.winfo_height()
        total = max(len(self.paths), 1)
        frac = 1.0 / total
        if e.y <= 16:
            self.tree.yview_moveto(max(0.0, self.tree.yview()[0] - frac))
        elif e.y >= h - 16:
            self.tree.yview_moveto(min(1.0, self.tree.yview()[0] + frac))
        row = self.tree.identify_row(e.y)
        cur = self.tree.index(row) if row else len(self.paths) - 1  # 空白区视为拖到末尾
        if cur != st["last"] and cur not in st["sel"]:
            direction = 1 if cur > st["last"] else -1
            self.paths, new_sel = reorder_block(self.paths, st["sel"], cur, direction)
            self.rotations, _ = reorder_block(self.rotations, st["sel"], cur, direction)
            self._refresh_list()
            self._select_indices(new_sel)
            st["sel"], st["last"] = new_sel, cur
        return "break"  # 屏蔽默认的拖动框选/自动扫描，避免与重排打架

    def _on_drag_release(self, e):
        if self._drag:
            self._drag = None
            self.tree.config(cursor="")

    def _move(self, delta):
        sel = self._sel_indices()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < len(self.paths):
            self.paths[i], self.paths[j] = self.paths[j], self.paths[i]
            self.rotations[i], self.rotations[j] = self.rotations[j], self.rotations[i]
            self._refresh_list()
            self._select_indices([j])

    def _rotate(self, delta):
        """对选中图片做 90° 旋转（delta 为正=逆时针/左转，为负=顺时针/右转）。"""
        sel = self._sel_indices()
        if not sel:
            return
        for i in sel:
            self.rotations[i] = (self.rotations[i] + delta) % 360
        self._refresh_list()
        self._select_indices(sel)

    def _clear(self):
        self.paths.clear()
        self.rotations.clear()
        self._refresh_list()

    def _refresh_list(self):
        # 同步旋转状态与图片列表长度（添加/移除后自动补齐）
        while len(self.rotations) < len(self.paths):
            self.rotations.append(0)
        del self.rotations[len(self.paths):]
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(self.paths):
            name = os.path.basename(p)
            r = self.rotations[i]
            if r:
                label = {90: "左转90°", 180: "转180°", 270: "右转90°"}[r]
                name += f"  [{label}]"
            self.tree.insert("", "end", text=name, image=self._thumb_for(i))
        self._schedule_preview()  # 列表增删/移动/旋转/清空后自动预览

    # ---------------- 列表缩略图 ----------------
    LIST_THUMB_PX = 32  # 缩略图边长（行高 40 = 32 + 上下留白）

    def _sel_indices(self) -> list[int]:
        """Treeview 当前选中项 → 按显示顺序的行索引列表。"""
        return sorted(self.tree.index(iid) for iid in self.tree.selection())

    def _select_indices(self, idxs: list[int]):
        """按行索引设置 Treeview 选中并保证首项可见。"""
        children = self.tree.get_children()
        idxs = [i for i in idxs if 0 <= i < len(children)]
        if not idxs:
            return
        self.tree.selection_set([children[i] for i in idxs])
        self.tree.see(children[idxs[0]])

    def _thumb_for(self, i: int):
        """第 i 张图的列表缩略图（带缓存，key=(路径, 旋转角)；读取失败给灰色占位）。"""
        p = self.paths[i]
        rot = self.rotations[i] if i < len(self.rotations) else 0
        key = (p, rot)
        ph = self._thumbs.get(key)
        if ph is not None:
            return ph
        size = (self.LIST_THUMB_PX, self.LIST_THUMB_PX)
        try:
            im = Image.open(p)
            im.draft("RGB", (256, 256))  # JPEG 低分辨率快解，大图不必全量解码
            im = ImageOps.exif_transpose(im)
            for _ in range(rot // 90):
                im = im.transpose(Image.ROTATE_90)
            im.thumbnail(size)
            ph = ImageTk.PhotoImage(im)
        except Exception:
            ph = ImageTk.PhotoImage(Image.new("RGB", size, "#c8c8c8"))
        self._thumbs[key] = ph
        return ph

    def _open_images(self):
        imgs = []
        for i, p in enumerate(self.paths):
            # 1) EXIF 方向自动转正（顺带移除 orientation 标签，后续不会重复旋转）
            im = ImageOps.exif_transpose(Image.open(p))
            # 2) 手动旋转（90° 整数倍 transpose，无插值）
            rot = self.rotations[i] if i < len(self.rotations) else 0
            for _ in range(rot // 90):
                im = im.transpose(Image.ROTATE_90)
            imgs.append(im)
        return imgs

    # ---------------- 预览（自动刷新 + 防抖） ----------------
    def _schedule_preview(self, delay_ms: int = 200):
        """防抖调度一次自动预览：延迟窗口内的连续变动只重算一次。"""
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(delay_ms, self._auto_preview)

    def _auto_preview(self):
        """自动刷新入口：静默执行，不弹任何对话框。"""
        self._preview_job = None
        if not self.paths:
            self._reset_preview()
            return
        try:
            self._render_preview()
        except Exception as e:
            # 选项暂时无效（如间隙输入到一半）等：只在状态行提示
            self.size_label.config(text=f"预览出错：{str(e)[:60]}")

    def _reset_preview(self):
        self._photo = None
        self._result_img = None
        self.preview_label.config(image="", text="（尚未拼接）")
        self.size_label.config(text="结果尺寸：—")

    def _render_preview(self):
        """执行一次预览渲染（打开图片 → 拼接 → 缩略图）。异常向上抛。"""
        imgs = self._open_images()
        try:
            out = self._do_stitch(imgs)
            self._result_img = out
            self.size_label.config(text=f"结果尺寸：{out.size[0]} × {out.size[1]}")
            # 缩略图
            maxw, maxh = 320, 340
            thumb = out.copy()
            thumb.thumbnail((maxw, maxh), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(thumb)
            self.preview_label.config(image=self._photo, text="")
        finally:
            for im in imgs:
                im.close()

    def _preview(self):
        """手动“刷新预览”按钮：保留原有提示弹窗。"""
        if not self.paths:
            messagebox.showwarning("提示", "请先添加图片。")
            return
        try:
            self._render_preview()
        except Exception as e:
            messagebox.showerror("预览失败", str(e))

    def _do_stitch(self, imgs):
        bg = (255, 255, 255, 0) if self.transparent.get() else (self.bg_color[0], self.bg_color[1], self.bg_color[2], 255)
        return stitcher.stitch(
            imgs,
            direction=self.direction.get(),
            align=self.align.get(),
            scale_mode=self.scale_mode.get(),
            gap=self.gap.get(),
            bg=bg,
        )

    def _save(self):
        if not self.paths:
            messagebox.showwarning("提示", "请先添加图片。")
            return
        out_path = filedialog.asksaveasfilename(
            title="保存拼接结果",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPG", "*.jpg *.jpeg"), ("WebP", "*.webp")]
        )
        if not out_path:
            return
        try:
            imgs = self._open_images()
            out = self._do_stitch(imgs)
            stitcher.save_result(out, out_path)
            for im in imgs:
                im.close()
            messagebox.showinfo("完成", f"已保存到：\n{out_path}\n尺寸：{out.size[0]} × {out.size[1]}")
        except Exception as e:
            messagebox.showerror("保存失败", str(e))


def _make_root() -> tk.Tk:
    """优先用支持拖拽的 TkinterDnD.Tk；tkdnd 加载失败时回退普通 Tk。"""
    global _DND_ACTIVE, _DND_INIT_ERROR
    _DND_ACTIVE = False
    _DND_INIT_ERROR = ""
    if _DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
            _DND_ACTIVE = True
            return root
        except Exception as e:
            _DND_INIT_ERROR = f"{type(e).__name__}: {e}"
    return tk.Tk()


def main():
    # tkinterdnd2 可用时用它的 Tk 子类，窗口才支持接收文件拖拽
    root = _make_root()
    try:
        # 尝试使用系统主题，体验更好
        from tkinter import ttk
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = StitcherApp(root)

    # 诊断开关供冻结版自检：设置 IMAGE_STITCHER_DND_DIAG=日志路径 后写状态并退出。
    diag_path = os.environ.get("IMAGE_STITCHER_DND_DIAG")
    if diag_path:
        try:
            package_version = root.tk.call("package", "require", "tkdnd") if _DND_ACTIVE else "未启用"
            text = (
                f"active={_DND_ACTIVE}\nimport_available={_DND_AVAILABLE}\n"
                f"registered={app._dnd_registered}\ntkdnd={package_version}\n"
                f"init_error={_DND_INIT_ERROR}\nregister_error={getattr(app, '_dnd_register_error', '')}\n"
            )
            with open(diag_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            with open(diag_path, "w", encoding="utf-8") as f:
                f.write(f"active={_DND_ACTIVE}\nerror={type(e).__name__}: {e}\n")
        root.destroy()
        return

    root.mainloop()


if __name__ == "__main__":
    main()
