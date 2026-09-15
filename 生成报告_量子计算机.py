# -*- coding: utf-8 -*-
"""
生成金刚石量子计算机实验报告 Word 文档
严格对齐示例 PDF 格式：
- Letter 纸张 (8.5 x 11 inches)
- 双栏排版（学术论文格式）
- 宋体(FandolSong)/黑体(FandolSong-Bold)/楷体(FandolKai) + Times New Roman
- 中文标题 18pt 黑体，作者 14pt 楷体，摘要 9pt
- 英文标题 16pt TNR Bold，英文摘要 10.5pt TNR
- 章节标题 12pt 黑体+TNR Bold（数字编号 1, 1.1, 1.2...）
- 页眉显示标题 + 页码
"""

from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

doc = Document()

# ============ 页面设置 ============
section = doc.sections[0]
section.page_width = Inches(8.5)   # Letter 宽度
section.page_height = Inches(11.0) # Letter 高度
section.top_margin = Cm(2.0)
section.bottom_margin = Cm(2.0)
section.left_margin = Cm(2.0)
section.right_margin = Cm(2.0)

# 设置双栏
sectPr = section._sectPr
cols = sectPr.find(qn('w:cols'))
if cols is None:
    cols = parse_xml(f'<w:cols {nsdecls("w")} w:num="2" w:space="425"/>')
    sectPr.append(cols)
else:
    cols.set(qn('w:num'), '2')
    cols.set(qn('w:space'), '425')

# ============ 页眉 ============
header = section.header
header.is_linked_to_previous = False
hp = header.paragraphs[0]
hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
hp_run = hp.add_run('金刚石量子计算机实验')
hp_run.font.name = 'Times New Roman'
hp_run.font.size = Pt(10.5)
hp_run.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

# 添加页码
# 在页眉右侧或用页脚
footer = section.footer
footer.is_linked_to_previous = False
fp = footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

# 添加页码字段
fldChar1 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
instrText = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> PAGE </w:instrText>')
fldChar2 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')

run = fp.add_run()
run.font.name = 'Times New Roman'
run.font.size = Pt(10.5)
run._element.append(fldChar1)
run2 = fp.add_run()
run2.font.name = 'Times New Roman'
run2.font.size = Pt(10.5)
run2._element.append(instrText)
run3 = fp.add_run()
run3.font.name = 'Times New Roman'
run3.font.size = Pt(10.5)
run3._element.append(fldChar2)

# ============ 默认样式 ============
style = doc.styles['Normal']
font = style.font
font.name = 'Times New Roman'
font.size = Pt(10.5)
font.color.rgb = RGBColor(0, 0, 0)
style.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
pf = style.paragraph_format
pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
pf.line_spacing = 1.2
pf.space_before = Pt(0)
pf.space_after = Pt(0)

def set_run_font(run, cn_font='宋体', en_font='Times New Roman', size=10.5, bold=False, italic=False):
    """设置中英文字体"""
    run.font.name = en_font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor(0, 0, 0)
    run.element.rPr.rFonts.set(qn('w:eastAsia'), cn_font)

def add_cn_title(text, size=18):
    """中文标题"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    set_run_font(run, '黑体', 'Times New Roman', size, True)
    return p

def add_authors(cn_text, en_text=''):
    """作者行"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(cn_text)
    set_run_font(run, '楷体', 'Times New Roman', 14, False)
    return p

def add_affiliation(text):
    """单位行"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run(text)
    set_run_font(run, '楷体', 'Times New Roman', 10.5, False)
    return p

def add_abstract(cn_text):
    """中文摘要"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run('摘要: ')
    set_run_font(run, '黑体', 'Times New Roman', 9, True)
    run2 = p.add_run(cn_text)
    set_run_font(run2, '宋体', 'Times New Roman', 9, False)
    return p

def add_keywords(text):
    """关键词"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run('关键词：')
    set_run_font(run, '黑体', 'Times New Roman', 9, True)
    run2 = p.add_run(text)
    set_run_font(run2, '宋体', 'Times New Roman', 9, False)
    return p

def add_en_title(text):
    """英文标题"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, '宋体', 'Times New Roman', 16, True)
    return p

def add_en_abstract(text):
    """英文摘要"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.15
    run = p.add_run('Abstract: ')
    set_run_font(run, '宋体', 'Times New Roman', 10.5, True)
    run2 = p.add_run(text)
    set_run_font(run2, '宋体', 'Times New Roman', 10.5, False)
    return p

def add_en_keywords(text):
    """英文关键词"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run('Keywords: ')
    set_run_font(run, '宋体', 'Times New Roman', 10.5, True)
    run2 = p.add_run(text)
    set_run_font(run2, '宋体', 'Times New Roman', 10.5, False)
    return p

def add_section_heading(num, text):
    """章节标题（数字编号）"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.2
    run = p.add_run(f'{num} ')
    set_run_font(run, '黑体', 'Times New Roman', 12, True)
    run2 = p.add_run(text)
    set_run_font(run2, '黑体', 'Times New Roman', 12, True)
    return p

def add_subsection_heading(num, text):
    """子章节标题"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(f'{num} ')
    set_run_font(run, '黑体', 'Times New Roman', 12, True)
    run2 = p.add_run(text)
    set_run_font(run2, '黑体', 'Times New Roman', 12, True)
    return p

def add_body(text, indent=True):
    """正文段落"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.2
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run(text)
    set_run_font(run, '宋体', 'Times New Roman', 10.5, False)
    return p

def add_bullet(text, bold_prefix=None):
    """项目符号段落"""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.74)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.2
    run0 = p.add_run('• ')
    set_run_font(run0, '宋体', 'Times New Roman', 10.5, False)
    if bold_prefix:
        run1 = p.add_run(bold_prefix)
        set_run_font(run1, '黑体', 'Times New Roman', 10.5, True)
    run2 = p.add_run(text)
    set_run_font(run2, '宋体', 'Times New Roman', 10.5, False)
    return p

def add_figure_caption(text):
    """图注"""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, '宋体', 'Times New Roman', 9, False)
    return p

# ============ 文档内容 ============

# 中文标题
add_cn_title('金刚石量子计算机实验', 18)

# 作者
add_authors('徐朝阳，张代宣')

# 单位
add_affiliation('武汉大学物理科学与技术学院，湖北省武汉市430072')

# 中文摘要
abstract_cn = '本实验报告旨在利用金刚石氮-空位色心搭建一个原型量子计算系统，并对其关键性能进行表征与验证。金刚石NV色心以其室温下卓越的相干特性、光学初始化和读出能力，成为实现实用化量子计算机极具潜力的物理平台。通过对单个NV色心进行光谱测量与顺磁共振测量，我们成功实现了电子自旋的初始化、相干操控（拉比振荡）、回波实验T2、实验动力学去耦和DJ实验。'
add_abstract(abstract_cn)

# 关键词
add_keywords('金刚石氮-空位色心；量子计算；量子比特；自旋操控；退相干时间')

# 英文标题
add_en_title('Diamond Quantum Computer Experiments')

# 英文单位
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(2)
run = p.add_run('School of physical science and technology, Wuhan University, Wuhan, 430072, China')
set_run_font(run, '宋体', 'Times New Roman', 10.5, False)

# 英文摘要
abstract_en = 'The purpose of this experiment is to construct a prototype quantum computing system using diamond nitrogen-vacancy centers and to characterize and validate its key performance. The diamond NV center, with its exceptional coherence properties at room temperature, along with its capabilities for optical initialization and readout, presents a highly promising physical platform for realizing practical quantum computers. Through spectral measurements and electron spin resonance measurements of a single NV center, we have successfully achieved electron spin initialization, coherent manipulation (Rabi oscillations), spin echo experiments (T2), dynamical decoupling experiments, and the DJ algorithm experiment.'
add_en_abstract(abstract_en)

# 英文关键词
add_en_keywords('Diamond nitrogen-vacancy center (NV center); Quantum computing; Qubit; Spin manipulation; Decoherence time')

# 正文
add_body('量子计算是一种遵循量子力学规律调控量子信息单元进行计算的新型计算模式。与经典计算机使用比特（0或1）作为信息基本单位不同，量子计算机使用量子比特（Qubit）作为基本单位。量子比特可以处于|0⟩和|1⟩的叠加态，并通过量子纠缠和量子干涉等特性，在处理特定问题时展现出超越经典计算机的巨大潜力，例如大数分解（Shor算法）和无序数据库搜索（Grover算法）。')
add_body('要实现量子计算，一个物理系统必须满足DiVincenzo判据，包括：良好的量子比特、初态制备、足够长的相干时间、通用量子逻辑门操作和量子态测量等。金刚石中的氮-空位（Nitrogen-Vacancy, NV）色心因其在室温下具有较长的电子自旋相干时间、可通过光探测磁共振（ODMR）技术进行初始化和读出的特性，成为实现量子计算的一个极具前景的物理平台。')
add_body('本实验利用基于金刚石NV色心的量子计算教学机，通过一系列基础实验，旨在理解和掌握量子比特的初始化、操控和读出方法，并最终实现Deutsch-Jozsa量子算法，直观展示量子计算的并行性优势。')

# 1 实验原理
add_section_heading('1', '实验原理')

add_subsection_heading('1.1', '金刚石NV色心')
add_body('NV色心是金刚石晶格中一个氮原子取代一个碳原子并与之相邻的一个空位所组成的点缺陷。其基态为自旋三重态，在零磁场下，|ms = 0⟩态与简并的|ms = ±1⟩态之间存在2.87GHz的零场劈裂。')

add_subsection_heading('1.2', '自旋态的初始化与读出')
add_bullet('使用532nm激光照射NV色心。由于|ms = ±1⟩态比|ms = 0⟩态有更高的概率通过系间窜越跃迁到中间单重态，并最终弛豫到|ms = 0⟩态，经过多个激光激发-弛豫周期后，NV色心被极化为|ms = 0⟩态。', '初始化：')
add_bullet('|ms = 0⟩态的荧光强度显著高于|ms = ±1⟩态。通过探测激光激发下的荧光强度，即可区分量子比特所处的状态。', '读出：')

add_subsection_heading('1.3', '自旋态的操控')
add_body('通过施加与自旋能级差共振的微波场，可以实现对电子自旋态的相干操控。在共振条件下（微波频率ω = ω0），量子态在|0⟩和|1⟩之间以拉比频率ω1做周期性振荡，其演化规律由薛定谔方程描述。')
add_bullet('当微波作用时间满足ω1t = π时，可实现|0⟩↔|1⟩的完全翻转，对应量子非门操作。', 'π脉冲：')
add_bullet('当微波作用时间满足ω1t = π/2时，可将量子比特从本征态制备到叠加态。', 'π/2脉冲：')

add_subsection_heading('1.4', 'Deutsch-Jozsa算法')
add_body('D-J算法用于判断一个函数是常函数（所有输入输出相同）还是平衡函数（一半输入输出0，另一半输出1）。对于n = 1的情况，经典算法最坏需要2次函数查询，而D-J量子算法仅需1次。其核心在于利用量子叠加性和相因子，通过量子线路的操作，最终通过对第一个量子比特的测量即可确定性地区分函数类型。')

# 2 实验装置
add_section_heading('2', '实验装置')
add_body('实验使用"金刚石量子计算教学机"，其主要由以下模块构成：')
add_bullet('产生532nm激光用于初始化和读出；通过共聚焦光路收集NV色心的荧光并由光电探测器转换为电信号。', '光学模块：')
add_bullet('产生频率和功率可调的微波信号，经放大和脉冲调制后，通过天线辐射至NV色心，用于操控自旋态。', '微波模块：')
add_bullet('产生精确定时的TTL控制脉冲，同步激光器、微波开关和数据采集卡的时序。', '控制与采集模块：')
add_bullet('通过Diamond I Studio软件控制整个实验流程。', '软件系统：')

# 3 实验内容与步骤
add_section_heading('3', '实验内容与步骤')

add_subsection_heading('3.1', '连续波ODMR实验')
add_body('目的：测量NV色心的光探测磁共振谱，确定其自旋共振频率。')
add_body('步骤：设置微波频率扫描范围，在连续激光照射和连续微波扫描下，采集荧光信号。')
add_figure_caption('图1: 连续波ODMR谱')
add_body('结果：测得两个共振频率MW1 = 2845 MHz，MW2 = 2898 MHz。')

add_subsection_heading('3.2', '拉比振荡实验')
add_body('目的：验证对量子比特的相干操控，并标定实现量子逻辑门所需的微波脉冲宽度。')
add_body('步骤：固定微波频率于一个共振频率，扫描微波脉冲的宽度，测量荧光信号。')
add_figure_caption('图2: 拉比振荡曲线，MW1')
add_figure_caption('图3: 拉比振荡曲线，MW2')
add_body('结果：从拉比振荡曲线中，在MW1波源下，测得π/2脉冲宽度为110 ns，π脉冲宽度为230 ns。在MW2波源下，测得π/2脉冲宽度为150 ns，π脉冲宽度为330 ns。')

add_subsection_heading('3.3', '回波实验')
add_body('目的：演示使用Hahn回波序列来抑制低频噪声的影响。')
add_body('步骤：执行(π/2)−τ−π−τ−(π/2)的脉冲序列，扫描第二个时间间隔τ。')
add_figure_caption('图4: 回波信号，MW1')
add_figure_caption('图5: 回波信号，MW2')
add_body('结果：观察到了回波现象，表明成功应用了动态解耦技术。')

add_subsection_heading('3.4', 'T2退相干时间测量实验')
add_body('目的：定量测量NV色心电子自旋的退相干时间T2。')
add_body('步骤：在Hahn回波序列中，扫描总自由演化时间τ，测量回波幅度的衰减曲线。')
add_figure_caption('图6: T2衰减曲线及指数拟合')
add_body('结果：通过拟合衰减曲线，得到退相干时间T2 = µs。')

add_subsection_heading('3.5', 'D-J算法实验')
add_body('目的：在NV色心系统上实验实现一阶Deutsch-Jozsa算法。')
add_body('步骤：通过特定的微波脉冲序列来构造四个不同的Uf Oracle门。')
add_figure_caption('图7: D-J1算法实验结果')
add_figure_caption('图8: D-J2算法实验结果')
add_figure_caption('图9: D-J3算法实验结果')
add_figure_caption('图10: D-J4算法实验结果')
add_body('结果：')
add_bullet('对于序列DJ1和DJ2，回波信号方向如图，判断为常函数。')
add_bullet('对于序列DJ3和DJ4，回波信号方向为如图，判断为平衡函数。')
add_body('实验结果与理论预言一致，成功演示了D-J算法。')

# 4 讨论与分析
add_section_heading('4', '讨论与分析')
add_body('1. 量子态操控：拉比振荡的成功观测，直接证明了我们能够对NV色心自旋进行相干的量子态操控。')
add_body('2. 退相干：T2实验结果表明量子叠加态会随着时间演化而衰减，体现了环境噪声对量子系统的影响。')
add_body('3. 量子优势：D-J算法实验以最直观的方式证明，对于特定问题，量子算法可以通过一次查询解决经典算法需要两次查询才能确定的问题。')

# 5 结论
add_section_heading('5', '结论')
add_body('本实验成功利用金刚石NV色心系统，完成了从量子比特性质表征、基本操作标定、相干特性研究到简单量子算法演示的全过程。实验结果与理论预期相符，加深了我们对量子计算基本原理和实验实现方法的理解。金刚石NV色心作为一种优秀的室温固态量子比特平台，在量子计算教学和研究中具有重要价值。')

# 参考文献
add_section_heading('', '参考文献')
add_body('[1] Nielsen M A, Chuang I L. Quantum Computation and Quantum Information[M]. Cambridge: Cambridge University Press, 2010.', indent=False)
add_body('[2] Doherty M W, Manson N B, Delaney P, et al. The nitrogen-vacancy colour centre in diamond[J]. Physics Reports, 2013, 528(1): 1-45.', indent=False)
add_body('[3] Deutsch D, Jozsa R. Rapid solution of problems by quantum computation[J]. Proceedings of the Royal Society of London A, 1992, 439(1907): 553-558.', indent=False)

# 保存
output_path = '实例实验报告/金刚石量子计算机实验报告.docx'
doc.save(output_path)
print(f'已生成: {output_path}')
