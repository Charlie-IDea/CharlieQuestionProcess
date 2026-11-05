"""Optional integration with the upstream MIT-licensed OMRChecker CLI.

Only an operator-configured, local repository path may be executed. No request
parameter controls the command, executable, template path or output directory.
"""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from .ai import ProviderUnavailable, ProviderFailure

def read_with_omrchecker(image,items):
    root=Path(os.environ['OMR_CHECKER_DIR']).resolve()
    if not (root/'main.py').is_file():
        raise ProviderUnavailable('OMR_CHECKER_DIR 未指向有效的 OMRChecker 仓库。')
    with TemporaryDirectory(prefix='teaching-omr-') as temp:
        directory=Path(temp)
        inputs=directory/'inputs'
        outputs=directory/'outputs'
        inputs.mkdir()
        image.save(inputs/'card.png')
        fields={}
        labels={}
        for index,item in enumerate(items):
            if item.snapshot['kind'] not in ('single','multiple'):
                continue
            if len(item.snapshot.get('options',[]))>4:
                raise ProviderFailure('当前 OMRChecker 适配模板只支持四选项，请使用内置识别器或人工复核。')
            key=f'q{index+1}'
            labels[key]=item.label
            fields[key]={'fieldType':'QTYPE_MCQ4','origin':[306,(155+index*101+10)*2],
                'fieldLabels':[key],'bubblesGap':86,'labelsGap':60}
        if not fields:
            return {}
        template={'pageDimensions':[image.width,image.height],'bubbleDimensions':[28,28],
            'preProcessors':[],'fieldBlocks':fields}
        (inputs/'template.json').write_text(json.dumps(template),encoding='utf-8')
        try:
            result=subprocess.run([sys.executable,str(root/'main.py'),'--inputDir',str(inputs),'--outputDir',str(outputs)],
                cwd=str(root),capture_output=True,timeout=90,check=False)
        except (OSError,subprocess.TimeoutExpired):
            raise ProviderFailure('OMRChecker 执行失败或超时。') from None
        if result.returncode:
            raise ProviderFailure('OMRChecker 未成功完成，请管理员检查其依赖与模板配置。')
        for path in outputs.rglob('*.csv'):
            with path.open(encoding='utf-8-sig',newline='') as file:
                for row in csv.DictReader(file):
                    if any(key in row for key in labels):
                        return {label:row.get(key,'').strip() for key,label in labels.items()}
        raise ProviderFailure('OMRChecker 未返回可用的识别结果。')
