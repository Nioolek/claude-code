#!/usr/bin/env python3
"""
Convert markdown report to PDF with visual flowcharts and Chinese font support.
Draws programmatic flowcharts using fpdf2 graphics primitives.
"""

import re
import os
from fpdf import FPDF

# ── Font Configuration ──────────────────────────────────────────────────
FONT_DIR = "C:/Windows/Fonts"
BODY_FONT = os.path.join(FONT_DIR, "msyh.ttc")       # Microsoft YaHei
BOLD_FONT = os.path.join(FONT_DIR, "msyhbd.ttc")     # Microsoft YaHei Bold
MONO_FONT = os.path.join(FONT_DIR, "simsun.ttc")     # SimSun (for code blocks)

# Page dimensions
PAGE_W = 210
PAGE_H = 297
MARGIN_L = 20
MARGIN_R = 20
MARGIN_T = 25
MARGIN_B = 20
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R  # 170mm

# Colors
C_H1 = (30, 60, 120)
C_H2 = (40, 80, 150)
C_H3 = (50, 90, 160)
C_H4 = (60, 100, 170)
C_BODY = (40, 40, 40)
C_CODE_BG = (240, 240, 240)
C_CODE_TXT = (30, 30, 30)
C_TBL_HEAD = (220, 230, 245)
C_TBL_BDR = (180, 180, 180)
C_HR = (200, 200, 200)

# Flowchart colors
C_FLOW_BOX = (230, 240, 255)       # Light blue box
C_FLOW_BOX2 = (255, 240, 230)      # Light orange box
C_FLOW_DEC = (255, 255, 220)       # Light yellow decision
C_FLOW_TERM = (255, 230, 230)      # Light red terminal
C_FLOW_LINE = (80, 80, 80)         # Arrow line
C_FLOW_TEXT = (30, 30, 30)         # Box text
C_FLOW_TITLE = (30, 60, 120)       # Flowchart title

# Font sizes
SZ_H1 = 18
SZ_H2 = 14
SZ_H3 = 12
SZ_H4 = 11
SZ_BODY = 10
SZ_CODE = 8.5
SZ_TABLE = 9
SZ_FOOTER = 8
SZ_FLOW = 7.5
SZ_FLOW_TITLE = 10

# Spacing
LH = 5.5  # line height
PARA_GAP = 3
H_SPACE_TOP = {1: 10, 2: 8, 3: 6, 4: 5}
H_SPACE_BOT = {1: 4, 2: 3, 3: 2, 4: 2}
LIST_INDENT = 8
CODE_INDENT = 5

# Flowchart dimensions
FLOW_BOX_W = 40
FLOW_BOX_H = 10
FLOW_DEC_W = 50
FLOW_DEC_H = 14
FLOW_ARROW_LEN = 8


class MarkdownPDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(True, MARGIN_B)

    def setup_fonts(self):
        self.add_font("YaHei", "", BODY_FONT)
        self.add_font("YaHei", "B", BOLD_FONT)
        self.add_font("SimSun", "", MONO_FONT)

    def footer(self):
        self.set_y(-15)
        self.set_font("YaHei", "", SZ_FOOTER)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"第 {self.page_no()} 页", align="C")

    # ── Drawing Primitives ──────────────────────────────────────────

    def draw_rect(self, x, y, w, h, fill_color=None, border_color=None, line_w=0.3):
        """Draw a rectangle with optional fill and border."""
        if fill_color:
            self.set_fill_color(*fill_color)
        if border_color:
            self.set_draw_color(*border_color)
        else:
            self.set_draw_color(80, 80, 80)
        self.set_line_width(line_w)
        style = "DF" if fill_color else "D"
        self.rect(x, y, w, h, style=style)

    def draw_text_in_box(self, x, y, w, h, text, font="YaHei", style="", size=SZ_FLOW,
                         color=C_FLOW_TEXT, align="C"):
        """Draw centered text inside a box area."""
        self.set_font(font, style, size)
        self.set_text_color(*color)
        lines = self._wrap_text(text, w - 2)
        total_h = len(lines) * (size * 0.38)
        start_y = y + (h - total_h) / 2
        for i, line in enumerate(lines):
            ly = start_y + i * (size * 0.38)
            if align == "C":
                self.set_xy(x, ly)
                self.cell(w, size * 0.38, line, align="C")
            elif align == "L":
                self.set_xy(x + 1, ly)
                self.cell(w - 2, size * 0.38, line, align="L")

    def _wrap_text(self, text, max_w):
        """Wrap text to fit within max_w width."""
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = ""
        for w in words:
            test = current + (" " if current else "") + w
            tw = self.get_string_width(test)
            if tw > max_w and current:
                lines.append(current)
                current = w
            else:
                current = test
        if current:
            lines.append(current)
        return lines if lines else [text]

    def draw_arrow(self, x1, y1, x2, y2, color=C_FLOW_LINE):
        """Draw an arrow from (x1,y1) to (x2,y2)."""
        self.set_draw_color(*color)
        self.set_line_width(0.5)
        self.line(x1, y1, x2, y2)
        # Arrowhead
        dx = x2 - x1
        dy = y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        if length == 0:
            return
        ux = dx / length
        uy = dy / length
        head_len = 2.5
        head_w = 1.5
        # Arrowhead tip at (x2,y2)
        p1x = x2 - head_len * ux + head_w * uy
        p1y = y2 - head_len * uy - head_w * ux
        p2x = x2 - head_len * ux - head_w * uy
        p2y = y2 - head_len * uy + head_w * ux
        self.set_fill_color(*color)
        self.polygon([(x2, y2), (p1x, p1y), (p2x, p2y)], style="F")

    def draw_down_arrow(self, x, y1, y2, color=C_FLOW_LINE):
        """Draw a vertical arrow from (x,y1) to (x,y2)."""
        self.draw_arrow(x, y1, x, y2, color)

    def draw_right_arrow(self, x1, y, x2, color=C_FLOW_LINE):
        """Draw a horizontal arrow from (x1,y) to (x2,y)."""
        self.draw_arrow(x1, y, x2, y, color)

    # ── Flowchart Components ────────────────────────────────────────

    def flow_box(self, cx, y, text, w=FLOW_BOX_W, h=FLOW_BOX_H, color=C_FLOW_BOX):
        """Draw a process box centered at cx."""
        x = cx - w / 2
        self.draw_rect(x, y, w, h, fill_color=color)
        self.draw_text_in_box(x, y, w, h, text)
        return x, y, w, h

    def flow_dec(self, cx, y, text, w=FLOW_DEC_W, h=FLOW_DEC_H, color=C_FLOW_DEC):
        """Draw a diamond decision shape centered at cx."""
        x = cx - w / 2
        # Diamond: draw polygon
        self.set_fill_color(*color)
        self.set_draw_color(80, 80, 80)
        self.set_line_width(0.3)
        pts = [(cx, y), (x + w, y + h / 2), (cx, y + h), (x, y + h / 2)]
        self.polygon(pts, style="DF")
        self.draw_text_in_box(x, y, w, h, text)
        return x, y, w, h

    def flow_term(self, cx, y, text, w=FLOW_BOX_W, h=FLOW_BOX_H, color=C_FLOW_TERM):
        """Draw a terminal (rounded) box - using rect with label."""
        x = cx - w / 2
        self.draw_rect(x, y, w, h, fill_color=color)
        self.draw_text_in_box(x, y, w, h, text)
        return x, y, w, h

    def flow_state(self, cx, y, text, w=FLOW_BOX_W, h=FLOW_BOX_H, color=C_FLOW_BOX):
        """Draw a state box (rounded corners simulated)."""
        x = cx - w / 2
        self.draw_rect(x, y, w, h, fill_color=color)
        self.draw_text_in_box(x, y, w, h, text)
        return x, y, w, h

    def flow_arrow(self, from_cx, from_y, from_h, to_cx, to_y, label=None):
        """Draw arrow from bottom of one box to top of another."""
        y1 = from_y + from_h
        y2 = to_y
        cx = (from_cx + to_cx) / 2
        if from_cx == to_cx:
            self.draw_arrow(from_cx, y1, to_cx, y2)
        else:
            # S-shaped path
            mid_y = (y1 + y2) / 2
            self.set_draw_color(*C_FLOW_LINE)
            self.set_line_width(0.5)
            self.line(from_cx, y1, from_cx, mid_y)
            self.line(from_cx, mid_y, to_cx, mid_y)
            self.line(to_cx, mid_y, to_cx, y2)
            # Arrowhead at end
            head_len = 2.5
            head_w = 1.5
            self.set_fill_color(*C_FLOW_LINE)
            self.polygon([
                (to_cx, y2),
                (to_cx - head_w, y2 - head_len),
                (to_cx + head_w, y2 - head_len)
            ], style="F")
        if label:
            self.set_font("YaHei", "", 6.5)
            self.set_text_color(120, 120, 120)
            lx = cx - 15
            ly = (y1 + y2) / 2 - 3
            self.set_xy(lx, ly)
            self.cell(30, 4, label, align="C")

    # ── Specific Flowcharts ─────────────────────────────────────────

    def draw_chart_title(self, title):
        """Draw a flowchart title and return the y position after it."""
        self.set_font("YaHei", "B", SZ_FLOW_TITLE)
        self.set_text_color(*C_FLOW_TITLE)
        y = self.get_y()
        self.cell(CONTENT_W, 7, title, align="C")
        self.ln(9)
        return self.get_y()

    def flowchart_task_lifecycle(self):
        """Task lifecycle state machine."""
        cx = PAGE_W / 2
        cy = self.get_y()
        bw = 36
        bh = 9

        # Row 1: Pending
        self.flow_state(cx, cy, "Pending\n(待执行)", bw, bh, C_FLOW_BOX)
        fb_y = cy + bh

        # Row 2: Running
        r_y = cy + 18
        self.flow_state(cx, r_y, "Running\n(运行中)", bw, bh, C_FLOW_BOX)
        self.draw_arrow(cx, cy + bh, cx, r_y)
        rb_y = r_y + bh

        # Row 3: Three terminal states
        t_y = r_y + 20
        self.flow_state(cx - 30, t_y, "Completed\n(已完成)", bw, bh, C_FLOW_BOX2)
        self.flow_state(cx, t_y, "Failed\n(失败)", bw, bh, C_FLOW_TERM)
        self.flow_state(cx + 30, t_y, "Killed\n(终止)", bw, bh, C_FLOW_TERM)

        # Arrows from Running to terminal states
        self.draw_arrow(cx, rb_y, cx - 30, t_y)
        self.draw_arrow(cx, rb_y, cx, t_y)
        self.draw_arrow(cx, rb_y, cx + 30, t_y)

        # Feedback loop from terminal back to Pending (recreate)
        loop_y = t_y + bh + 6
        self.set_font("YaHei", "", 6.5)
        self.set_text_color(120, 120, 120)
        self.set_xy(cx - 25, loop_y)
        self.cell(50, 4, "terminated = completed|failed|killed", align="C")

        self.set_y(loop_y + 6)

    def flowchart_polling_eviction(self):
        """Task polling and eviction flow."""
        cx = PAGE_W / 2
        cur_y = self.get_y()
        bw = 44
        bh = 8
        gap = 14

        steps = [
            ("pollTasks() 开始", C_FLOW_BOX, "box"),
            ("遍历所有 running 任务", C_FLOW_BOX, "box"),
            ("读取磁盘输出增量", C_FLOW_BOX, "box"),
            ("生成偏移量补丁", C_FLOW_BOX, "box"),
            ("推入消息队列", C_FLOW_BOX, "box"),
            ("检查是否已完成", C_FLOW_DEC, "dec"),
        ]

        # Draw main vertical flow
        for i, (text, color, stype) in enumerate(steps):
            y = cur_y + i * gap
            if stype == "dec":
                self.flow_dec(cx, y, text, bw + 6, bh + 4, color)
            else:
                self.flow_state(cx, y, text, bw, bh, color)
            if i > 0:
                prev_y = cur_y + (i - 1) * gap
                prev_h = bh + 4 if steps[i - 1][2] == "dec" else bh
                self.draw_arrow(cx, prev_y + prev_h, cx, y)

        # Branch from "检查是否已完成"
        dec_y = cur_y + 5 * gap
        dec_h = bh + 4

        # Yes branch
        yes_x = cx + 35
        yes_y = dec_y + 8
        self.flow_state(yes_x, yes_y, "是 → 标记 notified", 36, bh, C_FLOW_BOX2)
        self.draw_arrow(cx + (bw + 6) / 2, dec_y + dec_h / 2, yes_x - 18, yes_y + bh / 2)
        # 30s grace
        grace_y = yes_y + 12
        self.flow_state(yes_x, grace_y, "等待 30s 宽限期", 36, bh, C_FLOW_BOX2)
        self.draw_arrow(yes_x, yes_y + bh, yes_x, grace_y)
        # Evict
        evict_y = grace_y + 12
        self.flow_state(yes_x, evict_y, "从 AppState 驱逐", 36, bh, C_FLOW_TERM)
        self.draw_arrow(yes_x, grace_y + bh, yes_x, evict_y)

        # No branch
        no_x = cx - 35
        no_y = dec_y + 8
        self.flow_state(no_x, no_y, "否 → 继续等待", 36, bh, C_FLOW_BOX)
        self.draw_arrow(cx - (bw + 6) / 2, dec_y + dec_h / 2, no_x + 18, no_y + bh / 2)
        # Loop back up
        self.set_draw_color(*C_FLOW_LINE)
        self.set_line_width(0.5)
        # Curved path back to top
        loop_up_x = no_x - 15
        self.line(no_x, no_y + bh, loop_up_x, no_y + bh)
        self.line(loop_up_x, no_y + bh, loop_up_x, cur_y)
        # arrowhead
        self.set_fill_color(*C_FLOW_LINE)
        self.polygon([
            (loop_up_x, cur_y),
            (loop_up_x - 2, cur_y + 2.5),
            (loop_up_x + 2, cur_y + 2.5)
        ], style="F")

        self.set_font("YaHei", "", 6.5)
        self.set_text_color(120, 120, 120)
        self.set_xy(loop_up_x - 12, cur_y - 5)
        self.cell(24, 4, "1s 后重试", align="C")

        self.set_y(evict_y + bh + 6)

    def flowchart_api_retry(self):
        """API retry with exponential backoff timeline."""
        cx = PAGE_W / 2
        cur_y = self.get_y()
        bw = 30
        bh = 8

        # Title
        cur_y = self.draw_chart_title("API 重试：指数退避")

        # Draw timeline
        attempts = [
            (1, "0s", "立即"),
            (2, "~1s", "2^0"),
            (3, "~2s", "2^1"),
            (4, "~4s", "2^2"),
            (5, "~8s", "2^3"),
            (6, "~16s", "2^4"),
            (7, "~32s", "上限"),
            (8, "~32s", "上限"),
            (9, "~32s", "上限"),
            (10, "~32s", "上限"),
        ]

        start_x = MARGIN_L + 15
        bar_w = (CONTENT_W - 40) / len(attempts)

        # Draw bars
        max_w = 70  # max bar width in mm
        for i, (num, wait, formula) in enumerate(attempts):
            x = start_x + i * bar_w
            # Bar height proportional to wait time (log scale)
            if num == 1:
                bar_h = 3
            else:
                # Scale: 2^(num-2) mapped to 3-55mm
                bar_h = min(3 + (2 ** (num - 2)) * 0.5, max_w)

            # Draw bar
            self.set_fill_color(60, 100, 180)
            self.set_draw_color(40, 80, 150)
            self.set_line_width(0.2)
            self.rect(x, cur_y + 55 - bar_h, bar_w - 2, bar_h, style="DF")

            # Attempt number
            self.set_font("YaHei", "", 6.5)
            self.set_text_color(80, 80, 80)
            self.set_xy(x, cur_y + 57)
            self.cell(bar_w - 2, 4, f"第{num}次", align="C")

            # Wait time
            self.set_font("YaHei", "", 6)
            self.set_text_color(120, 120, 120)
            self.set_xy(x, cur_y + 61)
            self.cell(bar_w - 2, 4, wait, align="C")

        # Label
        self.set_font("YaHei", "", 7)
        self.set_text_color(*C_BODY)
        self.set_xy(MARGIN_L, cur_y + 66)
        self.cell(CONTENT_W, 4, "公式：等待时间 = BASE_DELAY × 2^(尝试次数-1)，上限 32s，+25% 随机抖动", align="C")

        self.set_y(cur_y + 74)

    def flowchart_circuit_breaker(self):
        """Circuit breaker state machine."""
        cx = PAGE_W / 2
        cur_y = self.get_y()
        bw = 36
        bh = 10

        # 3 states in a row
        s1_x = cx - 45
        s2_x = cx
        s3_x = cx + 45

        # Closed
        self.flow_state(s1_x, cur_y, "CLOSED\n(正常)", bw, bh, (200, 240, 200))
        s1_by = cur_y + bh

        # Half-Open
        self.flow_state(s2_x, cur_y, "HALF-OPEN\n(半开)", bw, bh, C_FLOW_DEC)
        s2_by = cur_y + bh

        # Open
        self.flow_state(s3_x, cur_y, "OPEN\n(断开)", bw, bh, C_FLOW_TERM)
        s3_by = cur_y + bh

        # Arrows: CLOSED → OPEN (on failure threshold)
        self.draw_arrow(s1_x, s1_by, s3_x, cur_y)

        # Arrows: OPEN → HALF-OPEN (timeout)
        self.draw_arrow(s3_x, s3_by, s2_x, cur_y)

        # Arrows: HALF-OPEN → CLOSED (success)
        self.draw_arrow(s2_x, s2_by, s1_x, cur_y)

        # Labels
        self.set_font("YaHei", "", 6.5)
        self.set_text_color(120, 120, 120)
        self.set_xy(s1_x + 5, s1_by + 1)
        self.cell(40, 4, "连续 3 次失败", align="C")
        self.set_xy(s3_x - 25, s3_by + 1)
        self.cell(40, 4, "超时后尝试", align="C")
        self.set_xy(s2_x - 20, s2_by + 1)
        self.cell(40, 4, "恢复成功", align="C")

        self.set_y(cur_y + bh + 14)

    def flowchart_agent_arch(self):
        """Agent orchestration 3-tier architecture."""
        cur_y = self.get_y()
        bw = 50
        bh = 14

        # Tier 1: User
        cx = PAGE_W / 2
        self.flow_state(cx, cur_y, "用户 (你)", bw, bh, (200, 230, 255))
        uy = cur_y + bh
        self.draw_arrow(cx, uy, cx, uy + 6)

        # Tier 2: Coordinator
        cy = cur_y + 24
        self.flow_state(cx, cy, "协调器 (主助手)", bw, bh, (180, 210, 240))
        cy2 = cy + bh
        self.draw_arrow(cx, cy2, cx, cy2 + 4)

        # Tier 3: Workers (horizontal row)
        wy = cy + 22
        workers = ["工作线程A", "工作线程B", "工作线程C", "..."]
        w_positions = [cx - 52, cx - 18, cx + 16, cx + 46]
        w_colors = [(230, 240, 255), (240, 230, 255), (255, 240, 230), (240, 255, 240)]

        for i, (wt, wc) in enumerate(zip(workers, w_positions)):
            self.flow_state(w_positions[i], wy, wt, 28, 10, w_colors[i])
            # Branch arrows from coordinator
            self.draw_arrow(cx, cy2, w_positions[i], wy)

        # Roles
        self.set_font("YaHei", "", 6.5)
        self.set_text_color(100, 100, 100)
        roles = ["(读文件)", "(查资料)", "(运行测试)", "(写代码)"]
        for i, (r, wp) in enumerate(zip(roles, w_positions)):
            self.set_xy(wp - 14, wy + 11)
            self.cell(28, 4, r, align="C")

        self.set_y(wy + 20)

    def flowchart_shutdown(self):
        """Graceful shutdown sequence."""
        cx = PAGE_W / 2
        cur_y = self.get_y()
        bw = 48
        bh = 8
        gap = 11

        steps = [
            ("关闭信号 (SIGINT/SIGTERM)", C_FLOW_TERM),
            ("设置标志防止重入", C_FLOW_BOX),
            ("启动故障安全计时器", C_FLOW_BOX2),
            ("终端清理 (鼠标/屏幕/键盘)", C_FLOW_BOX),
            ("打印恢复提示", C_FLOW_BOX),
            ("运行清理函数 (2s 超时)", C_FLOW_BOX),
            ("SessionEnd 钩子", C_FLOW_BOX),
            ("刷新分析数据 (500ms)", C_FLOW_BOX),
            ("forceExit() → SIGKILL 回退", C_FLOW_TERM),
        ]

        for i, (text, color) in enumerate(steps):
            y = cur_y + i * gap
            self.flow_state(cx, y, text, bw, bh, color)
            if i > 0:
                self.draw_arrow(cx, cur_y + (i - 1) * gap + bh, cx, y)

        # Timer label
        self.set_font("YaHei", "", 6.5)
        self.set_text_color(150, 80, 80)
        self.set_xy(cx + bw / 2 + 3, cur_y + 2 * gap + 1)
        self.cell(50, 8, "max(5s, 钩子超时 + 3.5s)", align="L")

        self.set_y(cur_y + len(steps) * gap + 4)

    def flowchart_agent_lifecycle(self):
        """Sub-agent complete lifecycle."""
        cx = PAGE_W / 2
        cur_y = self.get_y()
        bw = 36
        bh = 8
        gap = 12

        # Left column: main flow
        steps = [
            "AgentTool 被调用",
            "分配 agentId",
            "注册到 AppState",
            "构建隔离上下文",
            "query() LLM 循环",
            "发送 XML 通知",
            "REPL 注入通知",
            "30s 宽限期后驱逐",
        ]

        for i, text in enumerate(steps):
            y = cur_y + i * gap
            self.flow_state(cx - 25, y, text, bw, bh, C_FLOW_BOX)
            if i > 0:
                self.draw_arrow(cx - 25, y - gap + bh, cx - 25, y)

        # Right column: parallel details
        details = [
            "",
            "子控制器链接",
            "状态: pending",
            "克隆可变状态",
            "每 30s 进度摘要",
            "XML 格式",
            "协调器决策",
            "释放内存",
        ]

        for i, text in enumerate(details):
            if text:
                y = cur_y + i * gap
                self.set_font("YaHei", "", 6.5)
                self.set_text_color(100, 100, 100)
                self.set_xy(cx + 10, y + 1.5)
                self.cell(40, 6, text, align="L")

        self.set_y(cur_y + len(steps) * gap + 4)

    def flowchart_error_recovery(self):
        """Error recovery decision tree."""
        cur_y = self.get_y()
        cx = PAGE_W / 2

        # Draw error classification tree
        # Top: API error
        self.flow_state(cx, cur_y, "API 返回错误", 40, 9, C_FLOW_TERM)
        ey = cur_y + 9
        self.draw_down_arrow(cx, ey, ey + 4)

        # Decision: shouldRetry?
        dy = cur_y + 16
        self.flow_dec(cx, dy, "shouldRetry()?", 50, 12, C_FLOW_DEC)
        dyb = dy + 12
        self.draw_down_arrow(cx, dyb, dyb + 3)

        # Branch: retry vs abandon
        retry_x = cx - 40
        abandon_x = cx + 40
        ry = dy + 18

        # Retry side
        self.flow_state(retry_x, ry, "重试", 30, 8, (200, 240, 200))
        self.draw_arrow(cx, dyb, retry_x + 15, ry)

        # Abandon side
        self.flow_state(abandon_x, ry, "放弃", 30, 8, C_FLOW_TERM)
        self.draw_arrow(cx, dyb, abandon_x + 15, ry)

        # Retry subtypes
        subtypes = [
            ("529 → 最多3次\n然后模型回退", retry_x - 30, ry + 14),
            ("429 → 限流重试\n快速模式冷却", retry_x - 30, ry + 26),
            ("5xx → 标准指数退避", retry_x - 30, ry + 38),
            ("401 → 刷新令牌后重试", retry_x - 30, ry + 50),
            ("400 → 调整max_tokens", retry_x - 30, ry + 62),
        ]

        for text, sx, sy in subtypes:
            self.set_font("YaHei", "", 6.5)
            self.set_text_color(80, 80, 80)
            self.set_xy(sx, sy)
            self.cell(60, 6, text, align="L")

        self.set_y(ry + 74)

    # ── Text Rendering ──────────────────────────────────────────────

    def write_multi(self, text, font="YaHei", style="", size=SZ_BODY, color=C_BODY):
        self.set_font(font, style, size)
        self.set_text_color(*color)
        self.multi_cell(CONTENT_W, LH, text)
        self.set_x(MARGIN_L)

    def check_space(self, needed):
        if self.get_y() + needed > PAGE_H - MARGIN_B:
            self.add_page()

    def add_line(self, height=LH):
        self.ln(height)

    def _clean(self, text):
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        return text

    def render_heading(self, level, text):
        sizes = {1: SZ_H1, 2: SZ_H2, 3: SZ_H3, 4: SZ_H4}
        colors = {1: C_H1, 2: C_H2, 3: C_H3, 4: C_H4}
        st = H_SPACE_TOP.get(level, 5)
        sb = H_SPACE_BOT.get(level, 2)
        self.check_space(st + sizes[level] + sb)
        self.add_line(st)
        clean = self._clean(text)
        self.set_font("YaHei", "B", sizes[level])
        self.set_text_color(*colors[level])
        self.multi_cell(CONTENT_W, sizes[level] * 0.45, clean)
        self.set_x(MARGIN_L)
        if level == 1:
            self.set_draw_color(*colors[level])
            self.set_line_width(0.5)
            self.line(MARGIN_L, self.get_y(), PAGE_W - MARGIN_R, self.get_y())
            self.add_line(2)
        self.add_line(sb)

    def render_para(self, text):
        self.check_space(LH + 1)
        clean = self._clean(text)
        self.write_multi(clean, "YaHei", "", SZ_BODY, C_BODY)
        self.add_line(PARA_GAP)

    def render_bullet(self, items):
        self.check_space(len(items) * LH + 2)
        for item in items:
            text = self._clean(item)
            self.set_x(MARGIN_L + 3)
            self.set_font("YaHei", "", SZ_BODY)
            self.set_text_color(*C_BODY)
            self.cell(4, LH, "●")
            self.set_x(MARGIN_L + LIST_INDENT)
            self.multi_cell(CONTENT_W - LIST_INDENT - 2, LH, text)
            self.set_x(MARGIN_L)
            self.add_line(1)
        self.add_line(2)

    def render_ordered(self, items):
        self.check_space(len(items) * LH + 2)
        for i, item in enumerate(items):
            text = self._clean(item)
            self.set_xy(MARGIN_L + 3, self.get_y())
            self.set_font("YaHei", "", SZ_BODY)
            self.set_text_color(*C_BODY)
            self.cell(6, LH, f"{i+1}.")
            self.set_x(MARGIN_L + LIST_INDENT)
            self.multi_cell(CONTENT_W - LIST_INDENT - 2, LH, text)
            self.set_x(MARGIN_L)
            self.add_line(1)
        self.add_line(2)

    def render_code(self, code_lines):
        self.check_space(len(code_lines) * (SZ_CODE * 0.4 + 1) + 6)
        ch = len(code_lines) * (SZ_CODE * 0.4 + 1) + 4
        y = self.get_y()
        self.set_fill_color(*C_CODE_BG)
        self.rect(MARGIN_L + CODE_INDENT, y, CONTENT_W - CODE_INDENT * 2, ch, style="F")
        self.set_x(MARGIN_L + CODE_INDENT + 2)
        self.set_font("SimSun", "", SZ_CODE)
        self.set_text_color(*C_CODE_TXT)
        for line in code_lines:
            if self.get_y() > PAGE_H - MARGIN_B - 10:
                self.add_page()
                self.set_x(MARGIN_L + CODE_INDENT + 2)
                self.set_font("SimSun", "", SZ_CODE)
            self.multi_cell(CONTENT_W - CODE_INDENT * 2 - 4, SZ_CODE * 0.4 + 1, line.replace("\t", "    "))
            self.set_x(MARGIN_L + CODE_INDENT + 2)
        self.set_x(MARGIN_L)
        self.add_line(4)

    def render_table(self, headers, rows):
        cc = len(headers)
        cw = CONTENT_W / cc
        rh = SZ_TABLE * 0.45 + 3
        self.check_space(rh * (1 + len(rows)) + 4)

        def draw_cell(text, bold=False, fill=False):
            self.set_font("YaHei", "B" if bold else "", SZ_TABLE)
            if bold:
                self.set_text_color(*C_H1)
            else:
                self.set_text_color(*C_BODY)
            if fill:
                self.set_fill_color(*C_TBL_HEAD)
            tw = self.get_string_width(text)
            if tw > cw - 2:
                while tw > cw - 4 and len(text) > 1:
                    text = text[:-1]
                    tw = self.get_string_width(text + "...")
                text += "..."
            self.cell(cw, rh, text, border=1, align="C" if bold else "L",
                      fill=fill, new_x="RIGHT", new_y="LAST")

        self.set_draw_color(*C_TBL_BDR)
        for h in headers:
            draw_cell(h, bold=True, fill=True)
        self.add_line()
        self.set_x(MARGIN_L)
        for row in rows:
            for i, cell in enumerate(row):
                draw_cell(str(cell), bold=False)
            self.add_line()
            self.set_x(MARGIN_L)
        self.add_line(4)

    def render_hr(self):
        self.check_space(6)
        y = self.get_y() + 3
        self.set_draw_color(*C_HR)
        self.set_line_width(0.3)
        self.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
        self.set_y(y + 4)

    def render_blockquote(self, text):
        clean = self._clean(text)
        self.check_space(LH + 4)
        y = self.get_y()
        self.set_fill_color(200, 200, 200)
        self.rect(MARGIN_L, y, 2, LH + 2, style="F")
        self.set_x(MARGIN_L + 6)
        self.set_font("YaHei", "", SZ_BODY)
        self.set_text_color(100, 100, 100)
        self.multi_cell(CONTENT_W - 6, LH, clean)
        self.set_x(MARGIN_L)
        self.add_line(4)

    # ── Markdown Parser ─────────────────────────────────────────────

    def parse_and_render(self, md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        self.add_page()
        flowchart_section = 0

        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if not line.strip():
                i += 1
                continue

            # Heading
            hm = re.match(r'^(#{1,4})\s+(.+)$', line)
            if hm:
                level = len(hm.group(1))
                text = hm.group(2)
                self.render_heading(level, text)

                # Insert flowcharts at specific sections
                if "任务生命周期" in text and level == 2:
                    self.flowchart_task_lifecycle()
                elif "任务轮询与驱逐" in text and level == 2:
                    self.flowchart_polling_eviction()
                elif "重试策略" in text and level == 3:
                    self.flowchart_api_retry()
                elif "电路断路器" in text and level == 3:
                    self.flowchart_circuit_breaker()
                elif "三层架构" in text and level == 3:
                    self.flowchart_agent_arch()
                elif "工作线程的完整生命周期" in text and level == 3:
                    self.flowchart_agent_lifecycle()
                elif "分阶段关闭流程" in text and level == 3:
                    self.flowchart_shutdown()
                elif "错误场景分类" in text and level == 3:
                    # Place after the classification text
                    pass

                i += 1
                continue

            # HR
            if re.match(r'^---+\s*$', line):
                self.render_hr()
                i += 1
                continue

            # Code block
            if re.match(r'^```', line):
                code_lines = []
                i += 1
                while i < len(lines) and not re.match(r'^```', lines[i]):
                    code_lines.append(lines[i].rstrip())
                    i += 1
                i += 1
                self.render_code(code_lines)
                continue

            # Blockquote
            if line.startswith('> '):
                bq = []
                while i < len(lines) and lines[i].startswith('> '):
                    bq.append(lines[i][2:].rstrip())
                    i += 1
                self.render_blockquote(' '.join(bq))
                continue

            # Table
            if '|' in line and line.strip().startswith('|'):
                headers = [h.strip() for h in line.split('|') if h.strip()]
                i += 1
                if i < len(lines) and re.match(r'^[\s\|:\-]+$', lines[i]):
                    i += 1
                rows = []
                while i < len(lines) and '|' in lines[i] and lines[i].strip().startswith('|') and not re.match(r'^[\s\|:\-]+$', lines[i]):
                    row = [c.strip() for c in lines[i].split('|') if c.strip()]
                    if row:
                        rows.append(row)
                    i += 1
                self.render_table(headers, rows)
                continue

            # Bullet list
            bm = re.match(r'^(\s*)[\-\*]\s+(.+)$', line)
            if bm:
                items = [bm.group(2)]
                i += 1
                while i < len(lines):
                    nl = lines[i].rstrip()
                    m = re.match(r'^\s*[\-\*]\s+(.+)$', nl)
                    if m:
                        items.append(m.group(1))
                        i += 1
                    elif nl.strip() == '' and i + 1 < len(lines) and re.match(r'^\s*[\-\*]\s+', lines[i + 1]):
                        i += 1
                    else:
                        break
                self.render_bullet(items)
                continue

            # Ordered list
            om = re.match(r'^\s*\d+\.\s+(.+)$', line)
            if om:
                items = [om.group(1)]
                i += 1
                while i < len(lines):
                    nl = lines[i].rstrip()
                    m = re.match(r'^\s*\d+\.\s+(.+)$', nl)
                    if m:
                        items.append(m.group(1))
                        i += 1
                    elif nl.strip() == '' and i + 1 < len(lines) and re.match(r'^\s*\d+\.\s+', lines[i + 1]):
                        i += 1
                    else:
                        break
                self.render_ordered(items)
                continue

            # Paragraph
            para = [line]
            i += 1
            while i < len(lines):
                nl = lines[i].rstrip()
                if not nl.strip() or re.match(r'^(#{1,4}\s|```|---+\s*$|>\s|\s*[\-\*]\s+|\s*\d+\.\s+)', nl):
                    break
                if '|' in nl and nl.strip().startswith('|'):
                    break
                para.append(nl)
                i += 1
            pt = ' '.join(para)
            if pt.strip():
                self.render_para(pt)

    def save(self, output_path):
        self.output(output_path)


def main():
    md_path = os.path.join(os.path.dirname(__file__),
                           "claude-code-stability-analysis.md")
    pdf_path = md_path.replace(".md", ".pdf")

    pdf = MarkdownPDF()
    pdf.setup_fonts()
    pdf.parse_and_render(md_path)
    pdf.save(pdf_path)

    print(f"PDF generated: {pdf_path}")
    print(f"Pages: {pdf.page_no()}")


if __name__ == "__main__":
    main()