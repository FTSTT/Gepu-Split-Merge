import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import os
import tempfile

class ImagePreviewer:
    def __init__(self, root):
        self.root = root
        self.root.title("图片预览器 - 分割线随缩放保持位置")

        # 合并计数器，用于生成 merged_1, merged_2, ...
        self.merge_count = 1

        # 分割线“原始坐标系”列表：存储在整个图片集合的“原始累计高度”中的位置
        # （不再存储缩放后的画布坐标）
        self.dividers_original_positions = []

        # 存储图像信息: [pil_img, path, y_start, y_end, photo_obj]
        # - pil_img:       原始PIL图像，用于缩放
        # - path:          图片原始路径
        # - y_start/y_end: 此图在画布上的起止y(缩放后)，每次重绘会更新
        # - photo_obj:     Tk显示的PhotoImage对象，防垃圾回收
        self.image_data = []

        # ========== 顶部按钮区域 ==========
        toolbar_frame = tk.Frame(self.root)
        toolbar_frame.pack(side=tk.TOP, fill=tk.X)

        self.load_button = tk.Button(toolbar_frame, text="加载文件", command=self.load_images)
        self.load_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.merge_button = tk.Button(toolbar_frame, text="合并图片", command=self.save_merged_image)
        self.merge_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.clear_dividers_button = tk.Button(toolbar_frame, text="清除分割线", command=self.clear_dividers)
        self.clear_dividers_button.pack(side=tk.LEFT, padx=5, pady=5)

        # ========== 中间画布+滚动条区域 ==========
        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        # 可滚动画布
        self.canvas = tk.Canvas(self.canvas_frame, bg="white")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.scrollbar = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.config(yscrollcommand=self.scrollbar.set)

        # 绑定事件
        # - 点击画布添加分割线（并询问是否合并）
        self.canvas.bind("<Button-1>", self.add_divider)
        # - 主窗口尺寸变化时触发重绘
        self.root.bind("<Configure>", self.on_resize)
        # - 鼠标滚轮
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)

    # ========== 加载图片 ==========
    def load_images(self):
        """
        让用户选择图片文件，并按文件名中的数字顺序进行排序加载。
        同时将图像保存在内存。
        """
        file_paths = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("Image files", "*.jpg *.png *.jpeg *.tif *.bmp")]
        )
        if not file_paths:
            return

        self.merge_count=1
        # 假设文件名以数字开头，否则可能会出错（可根据需要改进）
        sorted_paths = sorted(file_paths, key=lambda x: int(os.path.basename(x).split('.')[0]))

        # 清空原有数据
        self.image_data.clear()
        self.dividers_original_positions.clear()
        self.canvas.delete("all")

        # 读取为PIL.Image并保存
        for path in sorted_paths:
            try:
                pil_img = Image.open(path).convert('RGB')
            except Exception as e:
                print(f"加载图片 {path} 出错：{e}")
                continue

            # 初始 y_start, y_end = 0, 0, photo_obj=None
            self.image_data.append([pil_img, path, 0, 0, None])

        self.display_images()

    # ========== 显示图片 & 重绘 ==========
    def display_images(self):
        """
        将已加载的图片按画布宽度等比例缩放并垂直排布。
        同时更新每张图在画布上的 y_start/y_end。
        """
        if not self.image_data:
            return

        self.canvas.delete("all")
        y_offset = 0
        canvas_width = self.canvas.winfo_width()

        # 逐张缩放显示
        for i, img_info in enumerate(self.image_data):
            pil_img, path, y_start, y_end, photo_obj = img_info
            orig_w, orig_h = pil_img.size

            # 避免极端情况
            if canvas_width <= 0:
                scale_w = 1
            else:
                scale_w = canvas_width

            scale_h = int(orig_h * (scale_w / orig_w))

            # Pillow 10+ 推荐使用下面方式
            img_resized = pil_img.resize((scale_w, scale_h), Image.Resampling.LANCZOS)

            # 转成Tk显示对象
            new_photo = ImageTk.PhotoImage(img_resized)

            # 在画布上绘制
            self.canvas.create_image(0, y_offset, anchor=tk.NW, image=new_photo)

            # 更新图像在画布上的范围
            self.image_data[i][2] = y_offset               # y_start
            self.image_data[i][3] = y_offset + scale_h     # y_end
            self.image_data[i][4] = new_photo              # 存储photo_obj防止回收

            y_offset += scale_h

        # 更新画布可滚动区域
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

        # 重新绘制分割线（使用原始坐标 -> 当前缩放坐标转换）
        self.redraw_dividers()

    def redraw_dividers(self):
        """
        重新绘制分割线：针对每个“原始坐标”计算在当前缩放后画布上的坐标。
        """
        for pos_original in self.dividers_original_positions:
            y_scaled = self.original_pos_to_scaled(pos_original)
            self.canvas.create_line(
                0, y_scaled,
                self.canvas.winfo_width(), y_scaled,
                fill="red", width=2, dash=(4, 2)
            )

    # ========== 分割线：添加 & 清除 ==========
    def add_divider(self, event):
        """
        在画布上点击时，将此点击点(缩放坐标)转换到原始坐标并存储。
        然后弹出对话框询问是否立即合并。
        """
        y_click_scaled = self.canvas.canvasy(event.y)

        # 转到原始坐标系
        y_click_original = self.scaled_pos_to_original(y_click_scaled)

        self.dividers_original_positions.append(y_click_original)

        # 重绘一次，让新分割线显示出来
        self.redraw_dividers()

        # 询问是否合并
        self.ask_merge_images()

    def clear_dividers(self):
        self.dividers_original_positions.clear()
        self.display_images()  # 清除后重新绘图

    # ========== 坐标转换函数 ==========
    def scaled_pos_to_original(self, y_scaled):
        """
        将当前画布上的 y(缩放坐标)转换回所有原图的“累计原始高度”中的位置。
        原理：找到点击落在哪张图片上，再折算回图片原始坐标，再加上之前图片的累积高度。
        """
        pos_original = 0
        # 累计扫描
        for pil_img, path, y_start, y_end, photo_obj in self.image_data:
            img_height_original = pil_img.size[1]
            if y_scaled >= y_start and y_scaled < y_end:
                # 点落在这一张图里
                scale_factor = img_height_original / (y_end - y_start)
                # 计算此图内的局部原始坐标
                local_y_original = (y_scaled - y_start) * scale_factor
                pos_original += local_y_original
                return pos_original
            else:
                # 没落在这张图，则把此图的原始高度全部加上
                pos_original += pil_img.size[1]

        # 若点击位置比最后一张图还要大，就返回最后一张图底部
        return pos_original

    def original_pos_to_scaled(self, pos_original):
        """
        将“累计原始高度”坐标转换成当前缩放后画布坐标。
        原理：逐图检查 pos_original 属于哪张图的范围内，再按比例转换。
        """
        accum = 0
        for pil_img, path, y_start, y_end, photo_obj in self.image_data:
            img_h_orig = pil_img.size[1]
            if pos_original <= accum + img_h_orig:
                # 属于这张图
                local_original = pos_original - accum
                scale_factor = (y_end - y_start) / img_h_orig
                return y_start + local_original * scale_factor
            accum += img_h_orig

        # 超过最后一张图底部时，返回画布最底
        return self.image_data[-1][3] if self.image_data else 0

    # ========== 合并操作 ==========
    def ask_merge_images(self):
        """
        弹出对话框，询问用户是否要对当前选区(最后两条分割线或从顶端到最后一条)进行合并保存。
        """
        if len(self.dividers_original_positions) >= 1:
            merge = messagebox.askyesno("合并图片", "是否保存当前选区的内容？")
            if merge:
                self.save_merged_image()

    def save_merged_image(self):
        """
        从原始坐标系里取最后一条分割线和倒数第二条分割线(或0)作为裁剪区，
        裁剪并垂直拼接所有图片的对应部分，最后在标题栏显示保存结果。
        不使用除 askyesno 以外的提示框。
        """
        # 如果没有分割线就不执行
        if not self.dividers_original_positions:
            # 不弹窗，静默返回
            return

        # 取最后一条分割线作为bottom，若有第二条则用倒数第二条，否则用0
        bottom = self.dividers_original_positions[-1]
        if len(self.dividers_original_positions) > 1:
            top = self.dividers_original_positions[-2]
        else:
            top = 0

        # 确保 top < bottom
        if top > bottom:
            top, bottom = bottom, top

        cropped_images = []
        cur_original_accum = 0  # 用来计算累积原始高度

        # 循环每张图
        for pil_img, path, y_start, y_end, photo_obj in self.image_data:
            h_orig = pil_img.size[1]
            img_top_orig = cur_original_accum
            img_bottom_orig = cur_original_accum + h_orig

            # 判断与选区 [top, bottom] 是否有交集
            if img_bottom_orig < top or img_top_orig > bottom:
                # 没有交集，跳过
                cur_original_accum += h_orig
                continue

            # 计算交集
            overlap_top = max(img_top_orig, top)
            overlap_bottom = min(img_bottom_orig, bottom)
            if overlap_bottom <= overlap_top:
                cur_original_accum += h_orig
                continue

            # 在当前图像的本地坐标系里进行crop
            local_crop_top = overlap_top - img_top_orig
            local_crop_bottom = overlap_bottom - img_top_orig

            region = pil_img.crop((0, local_crop_top, pil_img.size[0], local_crop_bottom))
            # 保存到临时文件
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            region.save(tmp_file.name)
            tmp_file.close()
            cropped_images.append(tmp_file.name)

            cur_original_accum += h_orig

        if not cropped_images:
            # 没有可合并的内容，也不弹窗
            return

        # 开始把所有临时图拼接起来
        segments = [Image.open(x) for x in cropped_images]
        widths, heights = zip(*(seg.size for seg in segments))

        total_width = max(widths)
        total_height = sum(heights)
        merged_im = Image.new('RGB', (total_width, total_height))

        y_offset = 0
        for seg in segments:
            merged_im.paste(seg, (0, y_offset))
            y_offset += seg.size[1]

        # 保存合并后的文件
        merged_path = f"merged_{self.merge_count}.png"
        merged_im.save(merged_path)
        self.merge_count += 1

        # 清理临时文件
        for f in cropped_images:
            os.unlink(f)

        # 在标题栏显示结果，不再弹出提示框
        self.root.title(f"图片已创建: {merged_path}")

    # ========== 事件回调 ==========
    def on_resize(self, event):
        """
        当主窗口大小变化时自动缩放并重绘图片、分割线。
        """
        if event.widget == self.root:
            self.display_images()

    def on_mouse_wheel(self, event):
        """
        鼠标滚轮滚动
        """
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")


if __name__ == "__main__":
    root = tk.Tk()
    # 设置一个默认窗口尺寸
    root.geometry("800x600")
    app = ImagePreviewer(root)
    root.mainloop()
