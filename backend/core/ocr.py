"""Optional PaddleOCR worker adapter. The GPU/CPU runtime is installed separately."""
from functools import lru_cache
from tempfile import TemporaryDirectory
from pathlib import Path
from .ai import ProviderUnavailable

@lru_cache(maxsize=1)
def pipeline():
    try:
        from paddleocr import PPStructureV3
    except ImportError:
        raise ProviderUnavailable('已选择PaddleOCR，但工作进程尚未安装 requirements-ocr.txt。')
    return PPStructureV3(use_doc_orientation_classify=True,use_doc_unwarping=True)

def parse_document(image):
    with TemporaryDirectory(prefix='teaching-ocr-') as directory:
        path=Path(directory)/'page.png'
        image.save(path)
        output=[]
        for result in pipeline().predict(input=str(path)):
            md=result.markdown
            if isinstance(md,dict):
                output.append(str(md.get('markdown_texts','')))
            else:
                output.append(str(md))
        return '\n'.join(output)
