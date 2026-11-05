from io import BytesIO
from PIL import ImageDraw
from PIL import Image
from .test_workflow import WorkflowFixture
from django.test import TestCase
from core.omr import create_card, read_card, WIDTH, HEIGHT, item_top
from core.models import SourceFile, SourcePage
from core.ai import ProviderFailure
import pypdfium2 as pdfium

class CardTests(WorkflowFixture,TestCase):
    # Keep only the four card-specific cases; base fixtures/helpers are reused.
    def render(self,paper,student):
        doc=pdfium.PdfDocument(create_card(paper,student))
        image=doc[0].render(scale=3).to_pil().convert('RGB')
        doc.close()
        return image
    def page(self,batch):
        file=SourceFile.objects.create(workspace=self.ws,batch=batch,file=self.image(),original_name='card.png',sha256='d'*64,role='student')
        return SourcePage.objects.create(workspace=self.ws,source_file=file,number=1,image=self.image(),width=600,height=800)
    def test_blank_card_requires_review(self):
        p=self.paper()
        batch=self.batch(route='card',paper=p)
        image=self.render(p,self.student)
        result=read_card(image,batch,self.page(batch))
        self.assertEqual(result['questions'][0]['student_answer'],'')
        self.assertTrue(result['questions'][0]['issues'])
    def test_marked_card_detects_b(self):
        p=self.paper()
        batch=self.batch(route='card',paper=p)
        image=self.render(p,self.student)
        draw=ImageDraw.Draw(image)
        sx,sy=image.width/WIDTH,image.height/HEIGHT
        x,y=(160+43)*sx,(item_top(0)+17)*sy
        draw.ellipse((x-6*sx,y-6*sy,x+6*sx,y+6*sy),fill='black')
        result=read_card(image,batch,self.page(batch))
        self.assertEqual(result['questions'][0]['student_answer'],'B')
        self.assertEqual(result['questions'][0]['printed_answer'],'B')
    def test_card_wrong_student_is_blocked(self):
        p=self.paper()
        batch=self.batch(route='card',paper=p)
        with self.assertRaises(ProviderFailure):
            read_card(self.render(p,self.other_student),batch,self.page(batch))
    def test_rotated_card_preserves_mark_mapping(self):
        p=self.paper()
        batch=self.batch(route='card',paper=p)
        image=self.render(p,self.student)
        draw=ImageDraw.Draw(image)
        sx,sy=image.width/WIDTH,image.height/HEIGHT
        x,y=(160+43)*sx,(item_top(0)+17)*sy
        draw.ellipse((x-6*sx,y-6*sy,x+6*sx,y+6*sy),fill='black')
        page=self.page(batch)
        for angle in [90,180,270]:
            result=read_card(image.rotate(angle,expand=True),batch,page)
            self.assertEqual(result['questions'][0]['student_answer'],'B',f'rotation={angle}')
    def test_card_missing_markers_is_blocked(self):
        p=self.paper()
        batch=self.batch(route='card',paper=p)
        image=self.render(p,self.student)
        image=image.crop((80,80,image.width-80,image.height-80))
        with self.assertRaises(ProviderFailure):
            read_card(image,batch,self.page(batch))
