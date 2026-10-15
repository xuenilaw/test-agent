"""One-time OSM capture using the Runner's viewport, semantic locators and tools."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from test_agent.schemas.plan import AtomicAction
from test_agent.tools.dom import Resolver, perform, capture_map

# Human-owned capture specification. No model chooses inputs or labels.
CAPTURES = [
    ('hamburg-berlin.png','Hamburg','Berlin','PASS','PASSED','baseline',False,False),
    ('hamburg-berlin-viewport.png','Hamburg','Berlin','PASS','PASSED','different viewport (1024x768)',True,False),
    ('hamburg-munich.png','Hamburg','Munich','NOT_PASS','FAILED','wrong destination',False,False),
    ('hamburg-potsdam.png','Hamburg','Potsdam','NOT_PASS','BLOCKED','near-miss next to Berlin; map labels may be ambiguous',False,False),
    ('berlin-hamburg.png','Berlin','Hamburg','NOT_PASS','FAILED','reversed origin/destination markers',False,False),
    ('bremen-berlin.png','Bremen','Berlin','NOT_PASS','FAILED','wrong origin',False,False),
    ('no-route.png',None,None,'NOT_PASS','BLOCKED','no calculated route',False,False),
    ('tiles-blank.png','Hamburg','Berlin','NOT_PASS','BLOCKED','tiles withheld; immediate screenshot after submit is unreadable',False,True),
]
HOLDOUT_CAPTURES = [
    ('hamburg-leipzig.png','Hamburg','Leipzig','NOT_PASS','FAILED','fresh wrong destination',False,False),
    ('rostock-berlin.png','Rostock','Berlin','NOT_PASS','FAILED','fresh wrong origin',False,False),
    ('berlin-hamburg-wide.png','Berlin','Hamburg','NOT_PASS','FAILED','reversed markers at a new viewport',True,False),
    ('hamburg-berlin-wide.png','Hamburg','Berlin','PASS','PASSED','fresh positive at a new viewport',True,False),
    ('hamburg-bernau.png','Hamburg','Bernau bei Berlin','NOT_PASS','BLOCKED','fresh near-miss north of Berlin',False,False),
]


async def capture_set(folder: Path, locators: Path, project_root: Path, *, headed=False, only=None, profile='original'):
    if profile not in {'original','holdout'}:
        raise ValueError('Unknown capture profile')
    presets = CAPTURES if profile == 'original' else HOLDOUT_CAPTURES
    captures = [c for c in presets if only is None or c[0] == only]
    if not captures:
        raise ValueError('Unknown capture name')
    if only is None and ((folder / 'labels.json').exists() or any((folder / 'images').glob('*.png'))):
        raise ValueError('Frozen capture set already exists; never overwrite it')
    if any((folder / 'images' / c[0]).exists() for c in captures):
        raise ValueError('Capture already exists; never overwrite it')
    resolver=Resolver.from_file(locators)
    if (project_root / '.browsers').exists():
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(project_root / '.browsers'))
    (folder / 'images').mkdir(parents=True,exist_ok=True)
    labels=json.loads((folder / 'labels.json').read_text()) if only and (folder / 'labels.json').exists() else []
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=not headed)
        try:
            for name,origin,destination,expected,ideal,why,alternate,blank in captures:
                alternate_viewport={'width':1440,'height':900} if profile=='holdout' else {'width':1024,'height':768}
                viewport=alternate_viewport if alternate else {'width':1280,'height':800}
                context=await browser.new_context(locale='en-GB',viewport=viewport)
                try:
                    page=await context.new_page(); page.set_default_timeout(15000)
                    if blank:
                        # Deliberately prevent basemap readability. No screenshot editing.
                        await page.route('**://*.tile.openstreetmap.org/**',lambda route:route.abort())
                        await page.route('**://tile.openstreetmap.org/**',lambda route:route.abort())
                    async def action(kind,target,value=None):
                        return await perform(page,resolver,AtomicAction(action=kind,target=target,value=value))
                    await action('navigate','OSM Website','https://www.openstreetmap.org/')
                    await action('click','route-planning control')
                    await action('select','travel-mode selector','Car')
                    if origin:
                        await action('fill','starting-point field',origin)
                        await action('fill','destination field',destination)
                        if blank:
                            await action('press','destination field','Enter')
                        else:
                            await action('click','request-directions button')
                    loc,_=await resolver.resolve(page,'vision map')
                    if not blank:
                        # Bounded wait for visible tile images, without retrying actions.
                        for _ in range(50):
                            ready=await loc.evaluate("el => [...el.querySelectorAll('img')].every(i => i.complete)")
                            if ready:
                                break
                            await asyncio.sleep(.2)
                    await capture_map(page,resolver,folder / 'images' / name)
                    labels.append(dict(file=name,route_shown=f'{origin} -> {destination}' if origin else 'No route',
                        requirement={'origin':'Hamburg','destination':'Berlin'},expected=expected,ideal=ideal,why=why))
                    (folder / 'capture.json').write_text(json.dumps(dict(completed=[l['file'] for l in labels],
                        profile=profile,default_viewport={'width':1280,'height':800},robustness_viewport=alternate_viewport,locators=resolver.specs,
                        loading_case='tile requests intentionally aborted; screenshot immediately after Enter'),indent=2))
                finally:
                    await context.close()
        finally:
            await browser.close()
    (folder / 'labels.json').write_text(json.dumps(labels,indent=2),encoding='utf-8')
    return labels
