"""图片横向/纵向拼接小工具 - 图形界面（tkinter）。

运行方式（在项目目录下）：
    uv run python app.py
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, colorchooser, messagebox, ttk
from PIL import Image, ImageTk

import stitcher

# 对齐方式内部值
ALIGN_VALUES = ("start", "center", "end")


class StitcherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("图片拼接小工具")
        root.geometry("760x560")
        root.resizable(True, True)

        self.paths: list[str] = []          # 已选图片路径
        self.bg_color = (255, 255, 255)      # 背景色 RGB
        self.transparent = tk.BooleanVar(value=False)  # 是否透明背景

        self._build_ui()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        # 顶部：方向 + 对齐 + 缩放
        opt_frame = ttk.LabelFrame(self.root, text="拼接选项", padding=8)
        opt_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=8)
        opt_frame.columnconfigure(1, weight=1)
        opt_frame.columnconfigure(3, weight=1)

        ttk.Label(opt_frame, text="方向：").grid(row=0, column=0, sticky="w")
        self.direction = tk.StringVar(value="horizontal")
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
        self.scale_mode = tk.StringVar(value="none")
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
        list_frame = ttk.LabelFrame(self.root, text="图片列表（可用 ▲▼ 调整顺序）", padding=8)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        self.listbox.grid(row=0, column=0, columnspan=5, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=5, sticky="ns")
        self.listbox.config(yscrollcommand=sb.set)

        btn_row = 1
        ttk.Button(list_frame, text="添加图片", command=self._add_images).grid(row=btn_row, column=0, padx=2, pady=4)
        ttk.Button(list_frame, text="移除", command=self._remove).grid(row=btn_row, column=1, padx=2, pady=4)
        ttk.Button(list_frame, text="上移 ▲", command=lambda: self._move(-1)).grid(row=btn_row, column=2, padx=2, pady=4)
        ttk.Button(list_frame, text="下移 ▼", command=lambda: self._move(1)).grid(row=btn_row, column=3, padx=2, pady=4)
        ttk.Button(list_frame, text="清空", command=self._clear).grid(row=btn_row, column=4, padx=2, pady=4)

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

        # 底部：操作
        action_frame = ttk.Frame(self.root, padding=8)
        action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(action_frame, text="拼接并保存", command=self._save).pack(side="right", padx=6)
        ttk.Button(action_frame, text="退出", command=self.root.destroy).pack(side="right")

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

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

    def _add_images(self):
        files = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tiff")]
        )
        for f in files:
            if f not in self.paths:
                self.paths.append(f)
        self._refresh_list()

    def _remove(self):
        sel = list(self.listbox.curselection())
        for i in reversed(sel):
            self.paths.pop(i)
        self._refresh_list()

    def _move(self, delta):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < len(self.paths):
            self.paths[i], self.paths[j] = self.paths[j], self.paths[i]
            self._refresh_list()
            self.listbox.selection_set(j)

    def _clear(self):
        self.paths.clear()
        self._refresh_list()

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.paths:
            self.listbox.insert(tk.END, os.path.basename(p))

    def _open_images(self):
        imgs = []
        for p in self.paths:
            imgs.append(Image.open(p))
        return imgs

    def _preview(self):
        if not self.paths:
            messagebox.showwarning("提示", "请先添加图片。")
            return
        try:
            imgs = self._open_images()
            out = self._do_stitch(imgs)
            self.size_label.config(text=f"结果尺寸：{out.size[0]} × {out.size[1]}")
            # 缩略图
            maxw, maxh = 320, 340
            thumb = out.copy()
            thumb.thumbnail((maxw, maxh), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(thumb)
            self.preview_label.config(image=self._photo, text="")
            for im in imgs:
                im.close()
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


def main():
    root = tk.Tk()
    try:
        # 尝试使用系统主题，体验更好
        from tkinter import ttk
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    StitcherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
