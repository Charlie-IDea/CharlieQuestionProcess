"""Versioned answer-card layout; all geometry is shared by writer and reader.

OpenCV performs alignment, QR decoding and conservative mark detection.
OMRChecker can be connected through OMR_CHECKER_DIR for an audited deployment;
the default reader has no external process or model dependency.
"""
import json
import os
from io import BytesIO
from math import ceil
from django.core import signing
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.utils import ImageReader
import qrcode
from PIL import Image
from .ai import ProviderFailure, extract_page, configured

WIDTH,HEIGHT=595.28,841.89
ITEMS_PER_PAGE=6
MARKERS=[(22,22),(WIDTH-22,22),(WIDTH-22,HEIGHT-22),(22,HEIGHT-22)]

def item_top(index):
    return 155+index*101

def create_card(paper,student):
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    out=BytesIO()
    pdf=canvas.Canvas(out,pagesize=(WIDTH,HEIGHT))
    items=list(paper.items.all())
    for page_index in range(ceil(len(items)/ITEMS_PER_PAGE)):
        pdf.setFont('STSong-Light',15)
        pdf.drawString(45,HEIGHT-55,paper.title[:30])
        pdf.setFont('STSong-Light',10)
        pdf.drawString(45,HEIGHT-78,f'姓名：{student.name}    第 {page_index+1} / {ceil(len(items)/ITEMS_PER_PAGE)} 页')
        pdf.drawString(45,HEIGHT-98,'请勿涂写定位点和二维码；选择题请填涂圆圈。')
        token=signing.dumps({'p':str(paper.id),'s':str(student.id),'n':page_index+1,'v':1},salt='answer-card',compress=True)
        qr=qrcode.make(token,error_correction=qrcode.constants.ERROR_CORRECT_L)
        pdf.drawImage(ImageReader(qr.get_image()),WIDTH-165,HEIGHT-145,120,120)
        for x,y in MARKERS:
            pdf.rect(x-5,HEIGHT-y-5,10,10,fill=1,stroke=0)
        for index,item in enumerate(items[page_index*ITEMS_PER_PAGE:(page_index+1)*ITEMS_PER_PAGE]):
            top=item_top(index)
            pdf.setFont('STSong-Light',11)
            pdf.drawString(45,HEIGHT-top,f'{item.label}. （{item.max_score}分）')
            if item.snapshot['kind'] in ('single','multiple'):
                option_count=max(4,min(8,len(item.snapshot.get('options',[]))))
                for option in range(option_count):
                    x=160+option*43
                    pdf.setFont('Helvetica',10)
                    pdf.drawString(x-3,HEIGHT-top+1,chr(65+option))
                    pdf.circle(x,HEIGHT-top-17,7,stroke=1,fill=0)
            else:
                pdf.rect(45,HEIGHT-top-76,WIDTH-90,65,stroke=1,fill=0)
        pdf.showPage()
    pdf.save()
    return out.getvalue()

def align_card(image):
    import cv2
    import numpy as np
    rgb=np.array(image.convert('RGB'))
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    _,binary=cv2.threshold(gray,100,255,cv2.THRESH_BINARY_INV)
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    h,w=gray.shape
    squares=[]
    for contour in contours:
        x,y,bw,bh=cv2.boundingRect(contour)
        area=cv2.contourArea(contour)
        if 0.000025*w*h<area<0.003*w*h and .7<bw/max(bh,1)<1.3 and area/max(bw*bh,1)>.7:
            squares.append((x+bw/2,y+bh/2))
    corners=[(0,0),(w,0),(w,h),(0,h)]
    chosen=[]
    for cx,cy in corners:
        nearby=[p for p in squares if abs(p[0]-cx)<w*.16 and abs(p[1]-cy)<h*.16]
        if not nearby:
            raise ProviderFailure('答题卡定位点不完整，请上传完整页面。')
        chosen.append(min(nearby,key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2))
    if len(set(chosen))!=4:
        raise ProviderFailure('答题卡定位失败，请重新拍摄。')
    target=np.float32([(x*2,y*2) for x,y in MARKERS])
    matrix=cv2.getPerspectiveTransform(np.float32(chosen),target)
    aligned=cv2.warpPerspective(rgb,matrix,(int(WIDTH*2),int(HEIGHT*2)),borderValue=(255,255,255))
    return Image.fromarray(aligned)

def read_card(image,batch,page):
    import cv2
    import numpy as np
    import zxingcpp
    original_codes=zxingcpp.read_barcodes(np.array(image.convert('RGB')))
    original_qr=next((item for item in original_codes if item.format==zxingcpp.BarcodeFormat.QRCode),None)
    if original_qr is not None and original_qr.orientation:
        image=image.rotate(original_qr.orientation,expand=True)
    aligned=align_card(image)
    arr=np.array(aligned)
    decoded=zxingcpp.read_barcodes(arr)
    token=next((item.text for item in decoded if item.format==zxingcpp.BarcodeFormat.QRCode),'')
    if not token:
        raise ProviderFailure('答题卡二维码无法识别，请拍摄更清晰图片。')
    try:
        payload=signing.loads(token,salt='answer-card')
    except signing.BadSignature:
        raise ProviderFailure('答题卡二维码签名无效。')
    if payload.get('v')!=1 or payload.get('p')!=str(batch.paper_id) or payload.get('s')!=str(batch.student_id):
        raise ProviderFailure('答题卡与所选学生或试卷不符，已阻止归档。')
    page_number=payload.get('n')
    if not isinstance(page_number,int) or page_number<1:
        raise ProviderFailure('答题卡页码无效。')
    items=list(batch.paper.items.all())[(page_number-1)*ITEMS_PER_PAGE:page_number*ITEMS_PER_PAGE]
    if not items:
        raise ProviderFailure('答题卡页码超出试卷范围。')
    # Persist the normalized image so returned crop coordinates share its coordinate system.
    buffer=BytesIO()
    aligned.save(buffer,format='JPEG',quality=94)
    from django.core.files.base import ContentFile
    old_name=page.image.name
    page.image.save('aligned.jpg',ContentFile(buffer.getvalue()),save=False)
    page.width,page.height=aligned.size
    page.save()
    if old_name:
        page.image.storage.delete(old_name)
    gray=cv2.cvtColor(arr,cv2.COLOR_RGB2GRAY)
    checker_answers=None
    if os.getenv('OMR_CHECKER_DIR'):
        from .omrchecker import read_with_omrchecker
        checker_answers=read_with_omrchecker(aligned,items)
    questions=[]
    for index,item in enumerate(items):
        top=item_top(index)
        snapshot=item.snapshot
        student_answer=''
        issues=[]
        confidence=0
        if snapshot['kind'] in ('single','multiple'):
            count=max(4,min(8,len(snapshot.get('options',[]))))
            marked=[]
            uncertain=False
            for option in range(count):
                x,y=int((160+option*43)*2),int((top+17)*2)
                patch=gray[y-8:y+8,x-8:x+8]
                ratio=float((patch<130).mean())
                if ratio>.55:
                    marked.append(chr(65+option))
                elif ratio>.15:
                    uncertain=True
            student_answer=''.join(marked)
            if checker_answers is not None:
                checker_answer=checker_answers.get(item.label,'')
                if checker_answer!=student_answer:
                    uncertain=True
                    issues.append('OMRChecker 与内置识别结果不一致，请人工核对。')
            if uncertain or not marked or (snapshot['kind']=='single' and len(marked)!=1):
                issues.append('空涂、多涂或擦除不清，请核对学生原件。')
            else:
                confidence=.98
        elif configured():
            crop=aligned.crop((90,int((top+8)*2),int((WIDTH-45)*2),int((top+78)*2)))
            result=extract_page(crop,'student','answered',batch)
            answers=result.get('questions',[])
            if len(answers)==1:
                student_answer=str(answers[0].get('student_answer',''))
            issues.append('手写作答需确认识别。')
        else:
            issues.append('未配置手写识别服务，请核对并补充作答。')
        questions.append({'number':item.label,'stem':snapshot['stem'],'kind':snapshot['kind'],
            'options':snapshot.get('options',[]),'tags':snapshot.get('tags',[]),
            'printed_answer':snapshot['answer'],'explanation':snapshot.get('explanation',''),
            'student_answer':student_answer,'student_answer_present':bool(student_answer),'confidence':confidence,
            'bbox':[45/WIDTH,(top-14)/HEIGHT,(WIDTH-45)/WIDTH,(top+80)/HEIGHT],
            'max_score':float(item.max_score),'score_is_printed':True,'issues':issues})
    return {'questions':questions,'card_page':page_number}
