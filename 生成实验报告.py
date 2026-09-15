#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实验报告生成脚本
按照示例PDF格式生成两份实验报告
"""

from docx import Document
from docx.shared import Pt, Cm, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def set_cell_border(cell, **kwargs):
    """
    设置表格单元格边框
    """
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    
    for edge in ('top', 'left', 'bottom', 'right'):
        edge_data = kwargs.get(edge)
        if edge_data:
            tag = 'w:{}'.format(edge)
            element = OxmlElement(tag)
            for key in ["sz", "val", "color", "space"]:
                if key in edge_data:
                    element.set(qn('w:{}'.format(key)), str(edge_data[key]))
            tcPr.append(element)

def add_page_border(doc):
    """
    添加页面边框
    """
    sectPr = doc.sections[0]._sectPr
    pgBorders = OxmlElement('w:pgBorders')
    pgBorders.set(qn('w:offsetFrom'), 'page')
    
    for border_name in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '4')
        border.set(qn('w:space'), '24')
        border.set(qn('w:color'), 'auto')
        pgBorders.append(border)
    
    sectPr.append(pgBorders)

def create_quantum_key_report():
    """
    创建量子密钥传输实验报告
    格式：A4纸，DengXian字体，中文编号
    """
    doc = Document()
    
    # 设置页面为A4
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    
    # 设置默认字体
    style = doc.styles['Normal']
    style.font.name = 'DengXian'
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 标题：量子密钥传输实验
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run('量子密钥传输实验')
    title_run.font.name = 'DengXian'
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 作者信息
    author = doc.add_paragraph()
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    author_run = author.add_run('范文轩 2022300002071')
    author_run.font.name = 'DengXian'
    author_run.font.size = Pt(10.5)
    author_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 日期
    date = doc.add_paragraph()
    date.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_run = date.add_run('2025 年10 月15 日')
    date_run.font.name = 'DengXian'
    date_run.font.size = Pt(10.5)
    date_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 一、实验目的
    section1_title = doc.add_paragraph()
    section1_run = section1_title.add_run('一、实验目的')
    section1_run.font.name = 'DengXian'
    section1_run.font.size = Pt(12)
    section1_run.font.bold = True
    section1_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    objectives = [
        '1. 了解量子密码的基本流程和安全性；',
        '2. 理解基于BB84 协议实现技术细节；',
        '3. 了解QKD 的研究进展;',
        '4. 了解量子密钥分发系统的实现方式和实验控制流程;',
        '5. 进行量子密钥传输实验。'
    ]
    for obj in objectives:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0)
        run = p.add_run(obj)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 二、主要实验仪器
    section2_title = doc.add_paragraph()
    section2_run = section2_title.add_run('二、主要实验仪器')
    section2_run.font.name = 'DengXian'
    section2_run.font.size = Pt(12)
    section2_run.font.bold = True
    section2_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    instrument_text = '红外QKD 教学机主要包括制备单个光子的单光子源，量子态的调制，实现光传输的光纤信道，实现单光子探测的单光子探测器，实现密钥分发收发同步的同步系统，以及整个系统的控制软件和密钥生成软件。'
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    run = p.add_run(instrument_text)
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 三、实验原理
    section3_title = doc.add_paragraph()
    section3_run = section3_title.add_run('三、实验原理')
    section3_run.font.name = 'DengXian'
    section3_run.font.size = Pt(12)
    section3_run.font.bold = True
    section3_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    principle_paras = [
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
    
    for text in principle_paras:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5)
        run = p.add_run(text)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 图注
    fig_caption = doc.add_paragraph()
    fig_caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fig_run = fig_caption.add_run('图1 密钥分发流程示意图')
    fig_run.font.name = 'DengXian'
    fig_run.font.size = Pt(10.5)
    fig_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 四、实验内容与步骤
    section4_title = doc.add_paragraph()
    section4_run = section4_title.add_run('四、实验内容与步骤')
    section4_run.font.name = 'DengXian'
    section4_run.font.size = Pt(12)
    section4_run.font.bold = True
    section4_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
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
        p.paragraph_format.left_indent = Cm(0)
        run = p.add_run(step)
        run.font.name = 'DengXian'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 五、实验数据
    section5_title = doc.add_paragraph()
    section5_run = section5_title.add_run('五、实验数据')
    section5_run.font.name = 'DengXian'
    section5_run.font.size = Pt(12)
    section5_run.font.bold = True
    section5_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 表1
    table1_caption = doc.add_paragraph()
    table1_caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t1_run = table1_caption.add_run('表1 发光二极管伏安特性与输出特性测量')
    t1_run.font.name = 'DengXian'
    t1_run.font.size = Pt(10.5)
    t1_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    table1 = doc.add_table(rows=5, cols=4)
    table1.style = 'Table Grid'
    
    # 表头
    headers = ['序号', '名称', '数据', '单位']
    for i, header in enumerate(headers):
        cell = table1.rows[0].cells[i]
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
    
    for row_idx, row_data in enumerate(data1, start=1):
        for col_idx, cell_data in enumerate(row_data):
            cell = table1.rows[row_idx].cells[col_idx]
            cell.text = cell_data
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in paragraph.runs:
                    run.font.name = 'DengXian'
                    run.font.size = Pt(10.5)
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 表2
    table2_caption = doc.add_paragraph()
    table2_caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t2_run = table2_caption.add_run('表2 密钥分发过程数据处理分析')
    t2_run.font.name = 'DengXian'
    t2_run.font.size = Pt(10.5)
    t2_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 创建表2（16列10行）
    table2 = doc.add_table(rows=10, cols=16)
    table2.style = 'Table Grid'
    
    # 表头行
    headers2 = ['位置', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15']
    for i, header in enumerate(headers2):
        cell = table2.rows[0].cells[i]
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
        ['B 探测', '0', '0', '1', '1', '1', '0', '0', '1', '0', '1', '1', '0', '0', '1', '1'],
        ['B 选基\n(+/×)', '×', '×', '+', '+', '+', '×', '+', '×', '×', '+', '×', '+', '×', '+', '+'],
        ['B 密钥', '0', '0', '1', '1', '1', '0', '0', '1', '0', '1', '1', '0', '0', '1', '1'],
        ['对基结果', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留', '保留']
    ]
    
    for row_idx, row_data in enumerate(rows_data, start=1):
        for col_idx, cell_data in enumerate(row_data):
            if col_idx < 16:
                cell = table2.rows[row_idx].cells[col_idx]
                cell.text = cell_data
                for paragraph in cell.paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    for run in paragraph.runs:
                        run.font.name = 'DengXian'
                        run.font.size = Pt(8)
                        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 六、实验总结
    section6_title = doc.add_paragraph()
    section6_run = section6_title.add_run('六、实验总结')
    section6_run.font.name = 'DengXian'
    section6_run.font.size = Pt(12)
    section6_run.font.bold = True
    section6_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    summary_text = '通过本次实验，我们成功完成了量子密钥传输实验。实验中，我们使用红外QKD 教学机，基于BB84 协议实现了量子密钥分发。通过对比发送端和接收端的数据，我们计算了系统的误码率，验证了量子密钥分发的安全性。实验结果表明，系统误码率低于理论安全界限11%，说明本次传输有效。同时，我们也学习了密钥分发过程中的数据处理方法，包括对基、纠错和保密放大等步骤。'
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    run = p.add_run(summary_text)
    run.font.name = 'DengXian'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'DengXian')
    
    # 保存文档
    doc.save('实例实验报告/量子密钥传输实验报告.docx')
    print('✓ 已生成：量子密钥传输实验报告.docx')

def create_quantum_computer_report():
    """
    创建量子计算机实验报告
    格式：学术论文格式，带页眉页脚，中英文摘要
    """
    doc = Document()
    
    # 设置页面
    section = doc.sections[0]
    section.page_width = Cm(21.59)  # Letter
    section.page_height = Cm(27.94)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    
    # 设置默认字体
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(10.5)
    
    # 页眉
    header = section.header
    header_para = header.paragraphs[0]
    header_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    header_run = header_para.add_run('金刚石量子计算机实验')
    header_run.font.name = 'FandolSong-Regular'
    header_run.font.size = Pt(10.5)
    header_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 标题
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run('金刚石量子计算机实验')
    title_run.font.name = 'FandolSong-Bold'
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Bold')
    
    # 作者
    author = doc.add_paragraph()
    author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    author_run = author.add_run('徐朝阳，张代宣')
    author_run.font.name = 'FandolKai-Regular'
    author_run.font.size = Pt(14)
    author_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolKai-Regular')
    
    # 单位
    affiliation = doc.add_paragraph()
    affiliation.alignment = WD_ALIGN_PARAGRAPH.CENTER
    aff_run = affiliation.add_run('武汉大学物理科学与技术学院，湖北省武汉市 430072')
    aff_run.font.name = 'FandolKai-Regular'
    aff_run.font.size = Pt(10.5)
    aff_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolKai-Regular')
    
    # 中文摘要
    abstract_title = doc.add_paragraph()
    abstract_title.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    abs_label = abstract_title.add_run('摘  要：')
    abs_label.font.name = 'FandolSong-Bold'
    abs_label.font.size = Pt(9)
    abs_label.font.bold = True
    abs_label._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Bold')
    
    abs_text = abstract_title.add_run('本实验报告旨在利用金刚石氮-空位色心搭建一个原型量子计算系统，并对其关键性能进行表征与验证。金刚石 NV 色心以其室温下卓越的相干特性、光学初始化和读出能力，成为实现实用化量子计算机极具潜力的物理平台。通过对单个NV 色心进行光谱测量与顺磁共振测量，我们成功实现了电子自旋的初始化、相干操控（拉比振荡）、回波实验 T2、实验动力学去耦和DJ 实验。')
    abs_text.font.name = 'FandolSong-Regular'
    abs_text.font.size = Pt(9)
    abs_text._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 关键词
    keywords = doc.add_paragraph()
    kw_label = keywords.add_run('关键词：')
    kw_label.font.name = 'FandolSong-Bold'
    kw_label.font.size = Pt(9)
    kw_label.font.bold = True
    kw_label._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Bold')
    
    kw_text = keywords.add_run('金刚石氮-空位色心；量子计算；量子比特；自旋操控；退相干时间')
    kw_text.font.name = 'FandolSong-Regular'
    kw_text.font.size = Pt(9)
    kw_text._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 英文标题
    en_title = doc.add_paragraph()
    en_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    en_title_run = en_title.add_run('Diamond Quantum Computer Experiments')
    en_title_run.font.name = 'Times New Roman'
    en_title_run.font.size = Pt(16)
    en_title_run.font.bold = True
    
    # 英文作者
    en_author = doc.add_paragraph()
    en_author.alignment = WD_ALIGN_PARAGRAPH.CENTER
    en_author_run = en_author.add_run('Xu Chaoyang, Zhang Daixuan')
    en_author_run.font.name = 'Times New Roman'
    en_author_run.font.size = Pt(10.5)
    
    # 英文单位
    en_aff = doc.add_paragraph()
    en_aff.alignment = WD_ALIGN_PARAGRAPH.CENTER
    en_aff_run = en_aff.add_run('School of physical science and technology, Wuhan University, Wuhan, 430072, China')
    en_aff_run.font.name = 'Times New Roman'
    en_aff_run.font.size = Pt(10.5)
    
    # 英文摘要
    en_abstract = doc.add_paragraph()
    en_abs_label = en_abstract.add_run('Abstract：')
    en_abs_label.font.name = 'Times New Roman'
    en_abs_label.font.size = Pt(10.5)
    en_abs_label.font.bold = True
    
    en_abs_text = en_abstract.add_run('The purpose of this experiment is to construct a prototype quantum computing system using diamond nitrogen-vacancy centers and to characterize and validate its key performance. The diamond NV center, with its exceptional coherence properties at room temperature, along with its capabilities for optical initialization and readout, presents a highly promising physical platform for realizing practical quantum computers. Through spectral measurements and electron spin resonance measurements of a single NV center, we have successfully achieved electron spin initialization, coherent manipulation (Rabi oscillations), spin echo experiments (T2), dynamical decoupling experiments, and the DJ algorithm experiment.')
    en_abs_text.font.name = 'Times New Roman'
    en_abs_text.font.size = Pt(10.5)
    
    # 英文关键词
    en_keywords = doc.add_paragraph()
    en_kw_label = en_keywords.add_run('Keywords: ')
    en_kw_label.font.name = 'Times New Roman'
    en_kw_label.font.size = Pt(10.5)
    en_kw_label.font.bold = True
    
    en_kw_text = en_keywords.add_run('Diamond nitrogen-vacancy center (NV center)；Quantum computing；Qubit；Spin manipulation；Decoherence time')
    en_kw_text.font.name = 'Times New Roman'
    en_kw_text.font.size = Pt(10.5)
    
    # 引言部分
    intro_paras = [
        '量子计算是一种遵循量子力学规律调控量子信息单元进行计算的新型计算模式。与经典计算机使用比特（0 或1）作为信息基本单位不同，量子计算机使用量子比特（Qubit）作为基本单位。量子比特可以处于|0>和|1>的叠加态，并通过量子纠缠和量子干涉等特性，在处理特定问题时展现出超越经典计算机的巨大潜力，例如大数分解（Shor 算法）和无序数据库搜索（Grover 算法）。',
        '要实现量子计算，一个物理系统必须满足DiVincenzo 判据，包括：良好的量子比特、初态制备、足够长的相干时间、通用量子逻辑门操作和量子态测量等。金刚石中的氮-空位（Nitrogen-Vacancy, NV）色心因其在室温下具有较长的电子自旋相干时间、可通过光探测磁共振（ODMR）技术进行初始化和读出的特性，成为实现量子计算的一个极具前景的物理平台。',
        '本实验利用基于金刚石NV 色心的量子计算教学机，通过一系列基础实验，旨在理解和掌握量子比特的初始化、操控和读出方法，并最终实现Deutsch-Jozsa 量子算法，直观展示量子计算的并行性优势。'
    ]
    
    for text in intro_paras:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)
        run = p.add_run(text)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 1 实验原理
    sec1_title = doc.add_paragraph()
    sec1_run = sec1_title.add_run('1  实验原理')
    sec1_run.font.name = 'Times New Roman'
    sec1_run.font.size = Pt(12)
    sec1_run.font.bold = True
    
    # 1.1
    sec1_1 = doc.add_paragraph()
    sec1_1_run = sec1_1.add_run('1.1  金刚石NV 色心')
    sec1_1_run.font.name = 'Times New Roman'
    sec1_1_run.font.size = Pt(10.5)
    sec1_1_run.font.bold = True
    
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('NV 色心是金刚石晶格中一个氮原子取代一个碳原子并与之相邻的一个空位所组成的点缺陷。其基态为自旋三重态，在零磁场下，|ms = 0>态与简并的|ms = ±1>态之间存在2.87GHz 的零场劈裂。')
    run.font.name = 'FandolSong-Regular'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 1.2
    sec1_2 = doc.add_paragraph()
    sec1_2_run = sec1_2.add_run('1.2  自旋态的初始化与读出')
    sec1_2_run.font.name = 'Times New Roman'
    sec1_2_run.font.size = Pt(10.5)
    sec1_2_run.font.bold = True
    
    bullet_items = [
        '初始化：使用532nm 激光照射NV 色心。由于|ms = ±1>态比|ms = 0>态有更高的概率通过系间窜越跃迁到中间单重态，并最终弛豫到|ms = 0>态，经过多个激光激发-弛豫周期后，NV 色心被极化为|ms = 0>态。',
        '读出：|ms = 0>态的荧光强度显著高于|ms = ±1>态。通过探测激光激发下的荧光强度，即可区分量子比特所处的状态。'
    ]
    
    for item in bullet_items:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(item)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 1.3
    sec1_3 = doc.add_paragraph()
    sec1_3_run = sec1_3.add_run('1.3  自旋态的操控')
    sec1_3_run.font.name = 'Times New Roman'
    sec1_3_run.font.size = Pt(10.5)
    sec1_3_run.font.bold = True
    
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('通过施加与自旋能级差共振的微波场，可以实现对电子自旋态的相干操控。在共振条件下（微波频率ω = ω0），量子态在|0>和|1>之间以拉比频率ω1 做周期性振荡，其演化规律由薛定谔方程描述。')
    run.font.name = 'FandolSong-Regular'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    bullet_items2 = [
        'π 脉冲：当微波作用时间满足ω1t = π 时，可实现|0><->|1>的完全翻转，对应量子非门操作。',
        'π/2 脉冲：当微波作用时间满足ω1t = π/2 时，可将量子比特从本征态制备到叠加态。'
    ]
    
    for item in bullet_items2:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(item)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 1.4
    sec1_4 = doc.add_paragraph()
    sec1_4_run = sec1_4.add_run('1.4  Deutsch-Jozsa 算法')
    sec1_4_run.font.name = 'Times New Roman'
    sec1_4_run.font.size = Pt(10.5)
    sec1_4_run.font.bold = True
    
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('D-J 算法用于判断一个函数是常函数（所有输入输出相同）还是平衡函数（一半输入输出0，另一半输出1）。对于n = 1 的情况，经典算法最坏需要2 次函数查询，而D-J 量子算法仅需1 次。其核心在于利用量子叠加性和相因子，通过量子线路的操作，最终通过对第一个量子比特的测量即可确定性地地区分函数类型。')
    run.font.name = 'FandolSong-Regular'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 2 实验装置
    sec2_title = doc.add_paragraph()
    sec2_run = sec2_title.add_run('2  实验装置')
    sec2_run.font.name = 'Times New Roman'
    sec2_run.font.size = Pt(12)
    sec2_run.font.bold = True
    
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('实验使用"金刚石量子计算教学机"，其主要由以下模块构成：')
    run.font.name = 'FandolSong-Regular'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    device_items = [
        '光学模块：产生532nm 激光用于初始化和读出；通过共聚焦光路收集NV 色心的荧光并由光电探测器转换为电信号。',
        '微波模块：产生频率和功率可调的微波信号，经放大和脉冲调制后，通过天线辐射至NV 色心，用于操控自旋态。',
        '控制与采集模块：产生精确定时的TTL 控制脉冲，同步激光器、微波开关和数据采集卡的时序。',
        '软件系统：通过Diamond I Studio 软件控制整个实验流程。'
    ]
    
    for item in device_items:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(item)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 3 实验内容与步骤
    sec3_title = doc.add_paragraph()
    sec3_run = sec3_title.add_run('3  实验内容与步骤')
    sec3_run.font.name = 'Times New Roman'
    sec3_run.font.size = Pt(12)
    sec3_run.font.bold = True
    
    experiments = [
        ('3.1  连续波ODMR 实验', '目的：测量NV 色心的光探测磁共振谱，确定其自旋共振频率。步骤：设置微波频率扫描范围，在连续激光照射和连续微波扫描下，采集荧光信号。', '图1: 连续波ODMR 谱', '结果：测得两个共振频率MW1 = 2845 MHz，MW2 = 2898 MHz。'),
        ('3.2  拉比振荡实验', '目的：验证对量子比特的相干操控，并标定实现量子逻辑门所需的微波脉冲宽度。步骤：固定微波频率于一个共振频率，扫描微波脉冲的宽度，测量荧光信号。', '图2: 拉比振荡曲线，MW1\n图3: 拉比振荡曲线，MW2', '结果：从拉比振荡曲线中，在MW1 波源下，测得π/2 脉冲宽度为110 ns，π 脉冲宽度为230 ns。在MW2 波源下，测得π/2 脉冲宽度为150 ns，π 脉冲宽度为330 ns。'),
        ('3.3  回波实验', '目的：演示使用Hahn 回波序列来抑制低频噪声的影响。步骤：执行(π/2)−τ−π−τ−(π/2)的脉冲序列，扫描第二个时间间隔τ。', '图4: 回波信号，MW1\n图5: 回波信号，MW2', '结果：观察到了回波现象，表明成功应用了动态解耦技术。'),
        ('3.4  T2 退相干时间测量实验', '目的：定量测量NV 色心电子自旋的退相干时间T2。步骤：在Hahn 回波序列中，扫描总自由演化时间τ，测量回波幅度的衰减曲线。', '图6: T2 衰减曲线及指数拟合', '结果：通过拟合衰减曲线，得到退相干时间T2 = [待填写] μs。'),
        ('3.5  D-J 算法实验', '目的：在NV 色心系统上实验实现一阶Deutsch-Jozsa 算法。步骤：通过特定的微波脉冲序列来构造四个不同的Uf Oracle 门。', '图7: D-J1 算法实验结果\n图8: D-J2 算法实验结果\n图9: D-J3 算法实验结果\n图10: D-J4 算法实验结果', '结果：\n• 对于序列DJ1 和DJ2，回波信号方向如图，判断为常函数。\n• 对于序列DJ3 和DJ4，回波信号方向为如图，判断为平衡函数。\n实验结果与理论预言一致，成功演示了D-J 算法。')
    ]
    
    for exp_title, exp_content, fig_caption, result in experiments:
        exp_p = doc.add_paragraph()
        exp_run = exp_p.add_run(exp_title)
        exp_run.font.name = 'Times New Roman'
        exp_run.font.size = Pt(10.5)
        exp_run.font.bold = True
        
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)
        run = p.add_run(exp_content)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
        
        # 图注
        fig_p = doc.add_paragraph()
        fig_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fig_run = fig_p.add_run(fig_caption)
        fig_run.font.name = 'FandolSong-Regular'
        fig_run.font.size = Pt(9)
        fig_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
        
        # 结果
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)
        run = p.add_run(result)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 4 讨论与分析
    sec4_title = doc.add_paragraph()
    sec4_run = sec4_title.add_run('4  讨论与分析')
    sec4_run.font.name = 'Times New Roman'
    sec4_run.font.size = Pt(12)
    sec4_run.font.bold = True
    
    discussion_items = [
        '1. 量子态操控：拉比振荡的成功观测，直接证明了我们能够对NV 色心自旋进行相干的量子态操控。',
        '2. 退相干：T2 实验结果表明量子叠加态会随着时间演化而衰减，体现了环境噪声对量子系统的影响。',
        '3. 量子优势：D-J 算法实验以最直观的方式证明，对于特定问题，量子算法可以通过一次查询解决经典算法需要两次查询才能确定的问题。'
    ]
    
    for item in discussion_items:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)
        run = p.add_run(item)
        run.font.name = 'FandolSong-Regular'
        run.font.size = Pt(10.5)
        run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 5 结论
    sec5_title = doc.add_paragraph()
    sec5_run = sec5_title.add_run('5  结论')
    sec5_run.font.name = 'Times New Roman'
    sec5_run.font.size = Pt(12)
    sec5_run.font.bold = True
    
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    run = p.add_run('本实验成功利用金刚石NV 色心系统，完成了从量子比特性质表征、基本操作标定、相干特性研究到简单量子算法演示的全过程。实验结果与理论预期相符，加深了我们对量子计算基本原理和实验实现方法的理解。金刚石NV 色心作为一种优秀的室温固态量子比特平台，在量子计算教学和研究中具有重要价值。')
    run.font.name = 'FandolSong-Regular'
    run.font.size = Pt(10.5)
    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'FandolSong-Regular')
    
    # 参考文献
    ref_title = doc.add_paragraph()
    ref_run = ref_title.add_run('参考文献')
    ref_run.font.name = 'Times New Roman'
    ref_run.font.size = Pt(10.5)
    ref_run.font.bold = True
    
    refs = [
        '[1] D\'Aloia A G, et al. Characterization of a commercial diamond sensor under alpha-particle irradiation. Diamond and Related Materials, 2023.',
        '[2] Kizil O, et al. Nitrogen-vacancy centers in diamond: A review. Diamond and Related Materials, 2022.',
        '[3] DiVincenzo D P. The physical implementation of quantumcomputing. Fortschritte der Physik, 2000, 48(9-11): 771-783.'
    ]
    
    for ref in refs:
        p = doc.add_paragraph()
        run = p.add_run(ref)
        run.font.name = 'Times New Roman'
        run.font.size = Pt(9)
    
    # 保存文档
    doc.save('实例实验报告/金刚石量子计算机实验报告.docx')
    print('✓ 已生成：金刚石量子计算机实验报告.docx')

if __name__ == '__main__':
    print('正在生成实验报告...')
    create_quantum_key_report()
    create_quantum_computer_report()
    print('\n✓ 两份实验报告已生成完成！')
