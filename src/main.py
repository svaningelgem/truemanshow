import asyncio
import logging
import re
import time
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import brotli
import pyppeteer
import requests
import browser_cookie3
from bs4 import BeautifulSoup
from pyppeteer import launch
from pyppeteer.network_manager import Request

link = 'https://www.jornluka.com/the-trueman-show-2/'
_CACHING_TIME = 24 * 60 * 60

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:101.0) Gecko/20100101 Firefox/101.0'
s.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
s.headers['Accept-Language'] = 'en-US,en;q=0.5'
s.headers['Accept-Encoding'] = 'gzip, deflate'
s.headers['DNT'] = '1'
s.headers['Connection'] = 'keep-alive'
s.headers['Upgrade-Insecure-Requests'] = '1'
s.headers['Sec-Fetch-Dest'] = 'document'
s.headers['Sec-Fetch-Mode'] = 'navigate'
s.headers['Sec-Fetch-Site'] = 'none'
s.headers['Sec-Fetch-User'] = '?1'
s.headers['Pragma'] = 'no-cache'
s.headers['Cache-Control'] = 'no-cache'


s.cookies = (
    browser_cookie3.load(domain_name='jornluka.com')
    # + browser_cookie3.load(domain_name='swarmcdn.com')
)


def _get_cache_file(url: str) -> Path:
    url = re.sub('^https?://', '', url)
    target = Path(__file__).parent / f'cache/{url}'
    if url.endswith('/'):
        target /= 'index.html'

    target.parent.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def _get_page(url: str, caching_time: Optional[int] = _CACHING_TIME) -> bytes:
    cache_file = _get_cache_file(url)
    if cache_file.exists() and (caching_time is None or time.time() - cache_file.stat().st_mtime < caching_time):
        return cache_file.read_bytes()

    response = s.get(url)
    assert response.status_code == 200, f'Response code is {response.status_code}... Did you refresh the page in your normal browser?'

    encoding = response.headers.get("Content-Encoding", '').lower()

    if encoding == 'br':
        final_content = brotli.decompress(response.content)
    elif encoding in ['gzip', '']:
        final_content = response.content
    else:
        raise AssertionError(f"I don't know {encoding}...")

    cache_file.write_bytes(final_content)
    return final_content


def _download_if_not_there(to_download, target) -> Path:
    current_target.mkdir(parents=True, exist_ok=True)

    tgt = current_target / target
    if not tgt.exists():
        tgt.write_bytes(
            _get_page(to_download, caching_time=None)
        )

    return tgt


def movie_part(request: Request, local: Path):
    response = request.response
    url = response.url
    if not re.search(r'\.mp\d$', url):
        logger.info('Event: request finished (%s)', url)
        return

    buffer = asyncio.get_running_loop().run_until_complete(response.buffer())
    logger.info('Got %d bytes', len(buffer))
    local.write_bytes(buffer)


async def pyppeteer_main(local_copy: Path):
    browser = await launch(headless=False, defaultViewport=None)
    page = await browser.newPage()
    await page.goto(str(local_copy).replace('\\', '/').replace('#', '%23'))

    # Nieuwsbrief inschrijven
    modal_dialog = await page.J('iframe')
    if modal_dialog:
        await page.evaluate("""
    var elements = document.querySelectorAll('iframe');
    for(var i=0; i< elements.length; i++){
        elements[i].parentNode.removeChild(elements[i]);
    }
""")

    # Set up monitoring of downloads
    # await page.setRequestInterception(True)
    # page.on('response', partial(movie_part, local=local_copy))

    # Scroll the video into view
    await page.hover('video')

    # Click it
    video = await page.J('video')
    await video.click()

    # Sleep long time
    await asyncio.sleep(180)

    await page.screenshot({'path': 'example.png'})
    await browser.close()


def _download_via_pyppeteer(to_download: Path, target):
    tgt = index_html.parent / target
    if tgt.exists():
        return

    asyncio.get_event_loop().run_until_complete(pyppeteer_main(to_download))


if __name__ == '__main__':
    main_page = _get_page(link)
    html = BeautifulSoup(main_page, "html.parser")
    target = _get_cache_file(link).parent

    for show in html.select('div.el-item.uk-panel'):
        link = urljoin(link, show.find('a').attrs['href'])
        image = urljoin(link, show.find(class_='el-image').attrs['data-src'])
        title = show.find(class_='el-title').text.strip()

        current_target = target / re.sub(r'[^- 0-9a-zA-Z#]', '', title)

        logger.info(f"Downloading: {title}")

        # Cache it
        _download_if_not_there(image, f'image{Path(image).suffix}')
        index_html = _download_if_not_there(link, 'index.html')
        _download_via_pyppeteer(index_html, 'movie.mp4')


    a = 1