"""Bounded local readers; the text model receives extracted text, not image pixels."""
from pathlib import Path
import csv
import io
import json
import os
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET

MAX_BYTES = 16 * 1024 * 1024
MAX_TEXT = 12000


def read_document(path, page_start=1, page_count=3):
    target = Path(path).expanduser().resolve(strict=True)
    if not target.is_file() or target.stat().st_size > MAX_BYTES:
        raise ValueError('Choose a file up to 16 MB.')
    result = {'success': True, 'path': str(target), 'name': target.name}
    if target.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(str(target))
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('This PDF is password-protected. Supply an unlocked copy.')
        start = max(1, int(page_start)) - 1
        count = max(1, min(int(page_count), 5))
        if start >= len(reader.pages):
            raise ValueError('Page is outside this PDF.')
        pieces=[]
        for number in range(start, min(start + count, len(reader.pages))):
            pieces.append(f'[Page {number + 1}]\n{(reader.pages[number].extract_text() or "")[:MAX_TEXT]}')
            if sum(map(len,pieces)) >= MAX_TEXT: break
        result.update(pages=len(reader.pages), page_start=start+1, output='\n\n'.join(pieces)[:MAX_TEXT], method='embedded PDF text')
        if not any((reader.pages[n].extract_text() or '').strip() for n in range(start,min(start+count,len(reader.pages)))):
            result['warning']='These pages have no embedded text. Scanned PDF OCR is not included.'
    elif target.suffix.lower() == '.docx':
        with zipfile.ZipFile(target) as archive:
            info=archive.getinfo('word/document.xml')
            if info.file_size > MAX_BYTES: raise ValueError('Expanded document is too large.')
            xml=ET.fromstring(archive.read(info))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text='\n'.join(''.join(p.itertext()) for p in xml.findall('.//w:p',ns))
        result.update(output=text[:MAX_TEXT], method='DOCX text')
    else:
        raw=target.read_bytes()
        if b'\0' in raw[:4000]: raise ValueError('This file is not a supported text document.')
        text=raw.decode('utf-8-sig',errors='replace')
        if target.suffix.lower()=='.csv':
            rows=[]
            omitted=False
            for index,row in enumerate(csv.reader(io.StringIO(text))):
                if index>=50:omitted=True;break
                rows.append(row)
            result.update(rows=rows,rows_truncated=omitted,output=json.dumps(rows,ensure_ascii=False)[:MAX_TEXT],method='CSV rows')
        else: result.update(output=text[:MAX_TEXT], method='UTF-8 text')
    result['truncated']=len(result['output']) >= MAX_TEXT or result.get('rows_truncated',False)
    return result


OCR_SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1)
function Await($operation,[Type]$resultType) { $task=$asTask.MakeGenericMethod($resultType).Invoke($null,@($operation));$task.Wait();$task.Result }
$file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:SYNTRA_OCR_IMAGE)) ([Windows.Storage.StorageFile])
$stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
  $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
  try {
    $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { throw 'No Windows OCR language is installed.' }
    $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    @{text=$result.Text;language=$engine.RecognizerLanguage.LanguageTag} | ConvertTo-Json -Compress
  } finally { $bitmap.Dispose() }
} finally { $stream.Dispose() }
'''


def read_image(path, cancel_event=None):
    from PIL import Image, ImageOps
    target=Path(path).expanduser().resolve(strict=True)
    if not target.is_file() or target.stat().st_size>MAX_BYTES: raise ValueError('Choose an image up to 16 MB.')
    with Image.open(target) as image:
        if image.width*image.height>40_000_000:raise ValueError('Image exceeds 40 megapixels.')
        result={'success':True,'path':str(target),'width':image.width,'height':image.height,'format':image.format,'method':'image metadata and Windows OCR','visual_understanding':False}
        prepared=ImageOps.exif_transpose(image).convert('RGB')
        prepared.thumbnail((4000,4000))
        with tempfile.TemporaryDirectory(prefix='syntra-ocr-') as folder:
            png=Path(folder)/'image.png';prepared.save(png)
            if os.name!='nt':
                result.update(output='',warning='Windows OCR is only available on Windows. Image dimensions were read.')
                return result
            script=Path(folder)/'read-image.ps1';script.write_text(OCR_SCRIPT,encoding='utf-8-sig')
            env=os.environ.copy();env['SYNTRA_OCR_IMAGE']=str(png)
            proc=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for attempt in range(120):
                    if cancel_event and cancel_event.is_set():raise InterruptedError('Image reading cancelled.')
                    try:
                        stdout,stderr=proc.communicate(timeout=.25);break
                    except subprocess.TimeoutExpired:continue
                else: raise TimeoutError('Windows OCR timed out.')
                if proc.returncode: raise RuntimeError(stderr.decode(errors='replace')[-600:])
                data=json.loads(stdout.decode('utf-8-sig',errors='replace'))
                result.update(output=str(data.get('text',''))[:MAX_TEXT],language=data.get('language'),ocr_available=True)
            except InterruptedError:raise
            except Exception as error:
                result.update(output='',ocr_available=False,warning='OCR unavailable: '+str(error)[:600])
            finally:
                if proc.poll() is None:proc.kill();proc.communicate()
    return result
