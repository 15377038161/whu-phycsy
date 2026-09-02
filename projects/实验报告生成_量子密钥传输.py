#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量子密钥传输实验报告生成脚本
按照示例PDF格式生成Word文档
"""

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.table import WD_TABLE_ALIGNMENT


def set_cell_border(cell, **kwargs):
    """设置单元格边框"""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for edge in ('start', 'top', 'end', 'bottom', 'insideH', 'insideV'):
        edge_data = kwargs.get(edge)
        if edge_data:
            element = OxmlElement(f'w:{edge}')
            element.set(qn('w:val'), 'single')
            element.set(qn('w:sz'), '4')
            element.set(qn('w:color'), '000000')
            element.set(qn('w:space'), '0')
            tcBorders.append(element)
    tcPr.append(tcBorders)


def create_quantum_key_report():
    """创建量子密钥传输实验报告"""
    doc = Document()
    
    # 设置页面为A4
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    
    # 设置默认字体
    style = doc.styles['Normal']
    style.font.name = 'DengXian'
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 标题 =====
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.space_after = Pt(12)
    run = title.add_run('量子密钥传输实验')
    run.font.name = 'DengXian'
    run.font.size = Pt(18)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 作者信息 =====
    author = doc.add_paragraph()
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    author.space_after = Pt(6)
    run = author.add_run('范文轩 2022300002071')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 日期 =====
    date = doc.add_paragraph()
    date.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date.space_after = Pt(18)
    run = date.add_run('2025 年10 月15 日')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 一、实验目的 =====
    heading1 = doc.add_paragraph()
    heading1.space_before = Pt(12)
    heading1.space_after = Pt(6)
    run = heading1.add_run('一、实验目的')
    run.font.name = 'DengXian'
    run.font.size = Pt(12)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    objectives = [
        '1. 了解量子密码的基本流程和安全性；',
        '2. 理解基于BB84 协议实现技术细节；',
        '3. 了解QKD 的研究进展;',
        '4. 了解量子密钥分发系统的实现方式和实验控制流程;',
        '5. 进行量子密钥传输实验。'
    ]
    
    for obj in objectives:
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = Pt(15.6)
        run = p.add_run(obj)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 二、主要实验仪器 =====
    heading2 = doc.add_paragraph()
    heading2.space_before = Pt(12)
    heading2.space_after = Pt(6)
    run = heading2.add_run('二、主要实验仪器')
    run.font.name = 'DengXian'
    run.font.size = Pt(12)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(15.6)
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('红外QKD 教学机主要包括制备单个光子的单光子源，量子态的调制，实现光传输的光纤信道，实现单光子探测的单光子探测器，实现密钥分发收发同步的同步系统，以及整个系统的控制软件和密钥生成软件。')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 三、实验原理 =====
    heading3 = doc.add_paragraph()
    heading3.space_before = Pt(12)
    heading3.space_after = Pt(6)
    run = heading3.add_run('三、实验原理')
    run.font.name = 'DengXian'
    run.font.size = Pt(12)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    principles = [
        '量子密钥分发实验中，协议实施的流程大致描述如下：',
        '发送方Alice 制备一系列的光子发送给接收方Bob，每个光子的偏振态独立随机地从水平偏振态|→〉、竖直偏振态|↑〉、右斜45 度偏振态|↗〉和左斜45 度偏振态|↖〉四个偏振态中选取，如果 Alice 发送光子的偏振态为水平偏振态|→〉或者竖直偏振态|↑〉，则称 Alice 选择+基制备光子，如果Alice 发送光子的偏振态是右斜45 度偏振态|↗〉或者左斜45 度偏振态|↖〉，则称Alice 选择×基制备光子。',
        '接收方Bob 与Alice 完全独立地随机选取+基和X 基测量Alice 发送过来光子的偏振态，并记录下测量到光子的位置信息。',
        'Alice 和 Bob 对基，即双方仅保留基相同（Alice 制备基和Bob 测量基）并且Bob 测量到光子位置的光子偏振态信息，双方基不同时则直接抛弃相关信息。',
        'Alice 和 Bob 将保留的光子偏振态信息转换成相应的密钥比特信息，即对基后保留的光子偏振态按水平偏振态|→〉和右斜 45 度偏振态|↗〉转换为比特"0"，竖直偏振态|↑〉和左斜45 度偏振态|↖〉转换为比特"1"。',
        'Alice 和 Bob 通过经典公开信道对上一步中获得的密钥比特进行处理，其过程主要分成纠错和保密放大来进行，纠错就是使得密钥比特一致，而保密放大（Privacy Amplification）就是将可能泄漏给窃听者的信息剔除掉。',
        '量子密钥分发系统中，用两位的bit 编码表示光子信息，其中个位bit 代表基矢信息，十位bit 代表密钥信息；例如：Alice 端水平偏振编码为00，垂直偏振编码为10，右斜45 度偏振编码为01，左斜45 度偏振编码为11；相应的Bob 端四路探测器探测到信号，分别也是按照上述编码方式进行编码。',
        '密钥分发的过程中，光子传输探测后，会得到一系列的这种两位编码的信息数据，如何从这些数据中提取出有用信息，需要原始数据（raw）经过对基（sift）、纠错（reconcile）、保密放大等过程，最后得到安全密钥（key），以保证密钥的安全性。当然，考虑到是否存在窃听，需要对系统的每次传输过程进行误码估计。以保证此次的传输数据有效。',
        'Alice 和 Bob 两端传输探测完成后会得到一系列两位编码的信息数据，首先需要对两端的数据进行对基，再对对基的数据进行比对，计算出系统的误码率。当误码率低于理论安全界限11%时，本次传输有效，继续进行后续处理过程。系统对基的过程实例如下图所示。'
    ]
    
    for text in principles:
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = Pt(15.6)
        p.paragraph_format.first_line_indent = Cm(0.74)
        run = p.add_run(text)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 图1标题
    fig1 = doc.add_paragraph()
    fig1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fig1.space_before = Pt(12)
    fig1.space_after = Pt(12)
    run = fig1.add_run('图1 密钥分发流程示意图')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 四、实验内容与步骤 =====
    heading4 = doc.add_paragraph()
    heading4.space_before = Pt(12)
    heading4.space_after = Pt(6)
    run = heading4.add_run('四、实验内容与步骤')
    run.font.name = 'DengXian'
    run.font.size = Pt(12)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    steps = [
        '1、发送端和接收端电路控制模块通电，启动QKD 软件；',
        '2、点击QKD 的发送端控制界面（Alice-Bob），勾选中间密钥输出功能；点击QKD 的运行按钮；待系统运行5-10 秒后，点击停止按钮。此时，记录下系统的平均误码率；',
        '3、在桌面的自由空间偏振文件夹中查看中间密钥输出的数据，输出的数据主要包括原始数据（raw），对基后数据（sift），纠错后数据（reconcile），最终安全密钥数据（key），对应的发送端分别为：transmitter-raw、transmitter-sift、transmitter-reconcile、transmitter-key，接收端分别为：receiver-raw、receiver-sift、receiver-reconcile、receiver-key；',
        '4、打开桌面上的量芯对比工具，选择文本比较，进入界面，点击最上方的会话选项，比较文件；',
        '5、使用文件对比工具分别打开transmitter-sift 和receiver-sift，然后从中选择部分数据（例如中间位置10 行，若总行数为1000，则提取数据比例为1%）进行两端的误码估计，数出错误的个数（黄色显示）并计算误码率。（例如总共100 个二进制数据，两端有5 个错误位，则误码率为5%）',
        '6、根据实验原理的系统对基过程，依照下表的模拟数据，进行填空，以了解和学习密钥分发过程的数据处理。',
        '7、关闭系统硬件和软件。'
    ]
    
    for step in steps:
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = Pt(15.6)
        run = p.add_run(step)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 五、实验数据 =====
    heading5 = doc.add_paragraph()
    heading5.space_before = Pt(12)
    heading5.space_after = Pt(6)
    run = heading5.add_run('五、实验数据')
    run.font.name = 'DengXian'
    run.font.size = Pt(12)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 表1
    table1_title = doc.add_paragraph()
    table1_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table1_title.space_after = Pt(6)
    run = table1_title.add_run('表1 发光二极管伏安特性与输出特性测量')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 创建表1
    table1 = doc.add_table(rows=5, cols=4)
    table1.style = 'Table Grid'
    table1.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # 表头
    headers = ['序号', '名称', '数据', '单位']
    header_row = table1.rows[0]
    for i, header in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = header
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in paragraph.runs:
                run.font.name = 'DengXian'
                run.font.size = Pt(10.5)
                run.font.bold = True
                run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 数据行
    data1 = [
        ['1', 'QKD 系统软件统计误码率', '5.457', '%'],
        ['2', 'QKD 系统误码估计采样率', '20', '%'],
        ['3', '手动提取对基后数据比例', '1.68', '%'],
        ['4', '对基后数据误码率', '10.9', '%']
    ]
    
    for i, row_data in enumerate(data1, start=1):
        row = table1.rows[i]
        for j, cell_text in enumerate(row_data):
            cell = row.cells[j]
            cell.text = cell_text
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.font.name = 'DengXian'
                    run.font.size = Pt(10.5)
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 添加空行
    doc.add_paragraph()
    
    # 表2
    table2_title = doc.add_paragraph()
    table2_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    table2_title.space_after = Pt(6)
    run = table2_title.add_run('表2 密钥分发过程数据处理分析')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 创建表2 (17列9行)
    table2 = doc.add_table(rows=9, cols=17)
    table2.style = 'Table Grid'
    table2.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # 表头
    headers2 = ['位置', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16']
    header_row2 = table2.rows[0]
    for i, header in enumerate(headers2):
        cell = header_row2.cells[i]
        cell.text = header
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in paragraph.runs:
                run.font.name = 'DengXian'
                run.font.size = Pt(9)
                run.font.bold = True
                run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 数据行
    rows_data = [
        ['A 编码', '00', '01', '10', '11', '11', '01', '00', '10', '10', '11', '01', '00', '00', '10', '11'],
        ['A 选基\n(+/×)', '+', '×', '+', '×', '×', '×', '+', '+', '+', '×', '×', '+', '+', '+', '×'],
        ['A 密钥', '0', '0', '1', '1', '1', '0', '0', '1', '1', '1', '0', '0', '0', '1', '1'],
        ['光偏振态', '→', '↗', '↑', '↖', '↖', '↗', '→', '↑', '↑', '↖', '↗', '→', '→', '↑', '↖'],
        ['Bob 选基', '×', '×', '+', '+', '+', '×', '+', '×', '×', '+', '×', '+', '×', '+', '+'],
        ['B 探测', '0', '0', '1', '1', '0', '0', '0', '0', '1', '1', '0', '0', '0', '1', '1'],
        ['对基', '', '√', '√', '', '', '√', '√', '', '', '', '√', '√', '', '√', '', '√'],
        ['A-Sift-key', '', '0', '1', '', '', '0', '0', '', '', '', '0', '0', '', '1', '', '0']
    ]
    
    for i, row_data in enumerate(rows_data, start=1):
        row = table2.rows[i]
        for j, cell_text in enumerate(row_data):
            cell = row.cells[j]
            cell.text = cell_text
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.font.name = 'DengXian'
                    run.font.size = Pt(9)
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # ===== 六、思考题 =====
    heading6 = doc.add_paragraph()
    heading6.space_before = Pt(12)
    heading6.space_after = Pt(6)
    run = heading6.add_run('六、思考题')
    run.font.name = 'DengXian'
    run.font.size = Pt(12)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 问题a
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(15.6)
    run = p.add_run('a) 误码率的误差来源有哪些？')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(15.6)
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('在量子密钥分发（QKD）实验中，误码率的误差来源包括以下几个方面：')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    sources = [
        '测量基不理想：偏振分束器等元件校准不准，造成测量基非完全正交。',
        '光学误差：在光纤传输中，由于应力、温度变化等因素，信道产生随机偏振旋转，改变光子的偏振态。',
        '光源不完美：实际使用弱相干态光源时，脉冲中存在多光子成分。'
    ]
    
    for source in sources:
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = Pt(15.6)
        p.paragraph_format.left_indent = Cm(1.5)
        run = p.add_run(source)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 问题b
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(15.6)
    p.paragraph_format.space_before = Pt(6)
    run = p.add_run('b) 对于随机性分析来说，采集数据的多少对随机性有什么影响？')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(15.6)
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('在随机性分析中，采集数据的数量对随机性评估的准确性、可靠性和深度有决定性的影响。数据量不足时，任何关于随机性的结论都是脆弱、不可靠甚至完全错误的。数据量越大，分析越可信。大样本能揭示微小的、系统性的非随机性，比如极其微弱的相关性、频率偏差或周期性。小样本则无法检测到这些细微缺陷。小样本只能分析非常短的相关性（例如，相邻比特之间的关系）。大样本才能探测长程相关性、周期性或复杂的模式，这些可能在数万甚至数百万比特之后才显现。')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 附实验数据记录单
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    run = p.add_run('附实验数据记录单')
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run.font.bold = True
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 保存文档
    output_path = '实例实验报告/量子密钥传输实验报告.docx'
    doc.save(output_path)
    print(f'✓ 已生成：{output_path}')
    return output_path


if __name__ == '__main__':
    output_path = create_quantum_key_report()
    print(f'报告已保存至：{output_path}')
