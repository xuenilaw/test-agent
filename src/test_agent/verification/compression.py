"""Deterministic, frozen JPEGs; original labelled PNGs are never modified."""
import hashlib
import io
import json
from PIL import Image

MAX_BYTES = 300_000
QUALITIES = (90,85,80,75,70)


def compress_image(data):
    image = Image.open(io.BytesIO(data)).convert('RGB')
    original_size = list(image.size)
    for width_limit in (None,1024,800,640,480,320):
        resized=image.copy()
        if width_limit:
            resized.thumbnail((width_limit,width_limit),Image.Resampling.LANCZOS)
        for quality in QUALITIES:
            output=io.BytesIO()
            resized.save(output,format='JPEG',quality=quality,subsampling=0,optimize=False)
            encoded=output.getvalue()
            if len(encoded) < MAX_BYTES:
                return encoded,dict(format='JPEG',quality=quality,subsampling=0,size_bytes=len(encoded),
                    original_dimensions=original_size,dimensions=list(resized.size),
                    source_sha256=hashlib.sha256(data).hexdigest(),sha256=hashlib.sha256(encoded).hexdigest())
    raise ValueError('Image cannot fit fixed compression policy')


def freeze_compressed(folder):
    from test_agent.verification.calibration import load_labels
    labels=load_labels(folder)
    output=folder/'compressed'
    output.mkdir(exist_ok=True)
    manifest={}
    for label in labels:
        data,meta=compress_image((folder/'images'/label.file).read_bytes())
        name=label.file.removesuffix('.png')+'.jpg'
        path=output/name
        if path.exists() and path.read_bytes()!=data:
            raise ValueError('Frozen JPEG differs: '+str(path))
        if not path.exists():
            path.write_bytes(data)
        manifest[name]=meta
    text=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'
    path=output/'manifest.json'
    if path.exists() and path.read_text()!=text:
        raise ValueError('Frozen compression manifest differs')
    if not path.exists():
        path.write_text(text)
    return manifest


def frozen_image(folder,label):
    path=folder/'compressed'/(label.file.removesuffix('.png')+'.jpg')
    manifest=json.loads((folder/'compressed/manifest.json').read_text())
    meta=manifest[path.name]
    if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256'] or hashlib.sha256(
            (folder/'images'/label.file).read_bytes()).hexdigest()!=meta['source_sha256']:
        raise ValueError('Frozen JPEG or PNG hash changed')
    return path,meta
