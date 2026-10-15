"""One screenshot proposal; a human-locator effect decides success."""
import hashlib
import io
import json
from typing import Annotated

from PIL import Image, ImageDraw
from pydantic import Field

from test_agent.schemas.plan import StrictModel
from test_agent.tools.dom import Blocked, LocatorSpec
from test_agent.verification.vision_providers import VisionError


class ClickObservation(StrictModel):
    found: bool
    x: float
    y: float
    confidence: Annotated[float, Field(ge=0, le=1)]
    summary: str = Field(min_length=1, max_length=400)


class VisionClickFallback:
    def __init__(self, resolver, specs, provider_factory, evidence_dir):
        self.resolver, self.specs = resolver, specs
        self.provider_factory, self.evidence_dir = provider_factory, evidence_dir
        self.attempted, self.events = set(), []

    async def __call__(self, page, target, original):
        data = self.specs.get(target)
        spec = LocatorSpec.model_validate(data) if data else None
        if not spec or not spec.vision_click_effect or target not in self.resolver.targets:
            raise original
        effect_spec = self.resolver.entries.get(spec.vision_click_effect)
        if effect_spec is None:
            raise Blocked('vision click requires a human effect locator', code='VISION_CONFIG')
        if target in self.attempted:
            raise Blocked('vision click already attempted', code='VISION_CLICK_LIMIT')
        self.attempted.add(target)
        folder = self.evidence_dir / ('click-' + str(len(self.events) + 1))
        folder.mkdir(parents=True)
        event = dict(target=target, locator_source='vision', healed=False, clicked=False,
                     status='BLOCKED', min_confidence=spec.vision_click.min_confidence,
                     effect_target=spec.vision_click_effect, image_size=[1280,800])
        self.events.append(event)
        reply = {}
        request = dict(description=self.resolver.targets[target], image_size=[1280,800],
                       coordinate_system='absolute pixels; top-left origin; no resizing',
                       output_schema=ClickObservation.model_json_schema())
        try:
            # A pre-existing effect could let a wrong click appear to succeed.
            effect = self.resolver.build_locator(page, effect_spec).filter(visible=True)
            if await effect.count() != 0:
                raise VisionError('CLICK_EFFECT_ALREADY_VISIBLE')
            image = await page.screenshot(path=str(folder/'viewport.png'), full_page=False, scale='css')
            picture = Image.open(io.BytesIO(image)).convert('RGB')
            if picture.size != (1280,800) or page.viewport_size != {'width':1280,'height':800}:
                raise VisionError('CONFIG', fields=['1280x800_viewport'])
            request['sha256'] = hashlib.sha256(image).hexdigest()
            provider = self.provider_factory()
            event.update(provider=getattr(provider,'provider_name',None),model=getattr(provider,'model',None))
            if not callable(getattr(provider, 'locate_click', None)):
                raise VisionError('CONFIG', fields=['coordinate_capable_provider'])
            reply = await provider.locate_click(image, self.resolver.targets[target])
            event.update({k:reply[k] for k in ('provider','model','api_host','upstream_host','upstream_provider') if k in reply})
            observation = ClickObservation.model_validate_json(reply.get('content', ''))
            event.update(observation.model_dump())
            if not 0 <= observation.x < 1280 or not 0 <= observation.y < 800:
                raise VisionError('CLICK_COORDINATES')
            marked = picture.copy()
            draw = ImageDraw.Draw(marked)
            x, y = observation.x, observation.y
            draw.ellipse((x-10,y-10,x+10,y+10),outline='red',width=3)
            draw.line((x-15,y,x+15,y),fill='red',width=2)
            draw.line((x,y-15,x,y+15),fill='red',width=2)
            marked.save(folder/'click-point.png')
            if not observation.found or observation.confidence < spec.vision_click.min_confidence:
                raise VisionError('CLICK_INCONCLUSIVE')
            await page.mouse.click(x,y)
            event['clicked'] = True
            try:
                await self.resolver.resolve(page,spec.vision_click_effect)
            except Blocked:
                raise VisionError('CLICK_NO_EFFECT') from None
            event['status'] = 'PASSED'
            self.resolver.metadata[target] = dict(healed=False, locator_source='vision')
            return dict(event)
        except Exception as exc:
            error = exc if isinstance(exc,VisionError) else VisionError('SCHEMA' if isinstance(exc,ValueError) else 'INTERNAL')
            event.update(code='VISION_'+error.code, **error.details)
            raise Blocked('Vision click blocked: '+event['code'], **{k:v for k,v in event.items() if k != 'status'}) from None
        finally:
            if isinstance(reply.get('content'),str):
                reply['content'] = reply['content'][:8000]
            for name, data in [('request',request),('response',reply),('decision',event)]:
                (folder/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
