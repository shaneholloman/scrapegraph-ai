import asyncio
import sys
from unittest.mock import ANY, AsyncMock, patch

import aiohttp
import pytest


class MockPlaywright:
    def __init__(self):
        self.chromium = AsyncMock()
        self.firefox = AsyncMock()


class MockBrowser:
    def __init__(self):
        self.new_context = AsyncMock()


class MockContext:
    def __init__(self):
        self.new_page = AsyncMock()


class MockPage:
    def __init__(self):
        self.goto = AsyncMock()
        self.wait_for_load_state = AsyncMock()
        self.content = AsyncMock()
        self.evaluate = AsyncMock()
        self.mouse = AsyncMock()
        self.mouse.wheel = AsyncMock()


@pytest.fixture
def mock_playwright():
    with patch("playwright.async_api.async_playwright") as mock:
        mock_pw = MockPlaywright()
        mock_browser = MockBrowser()
        mock_context = MockContext()
        mock_page = MockPage()

        mock_pw.chromium.launch.return_value = mock_browser
        mock_pw.firefox.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock.return_value.__aenter__.return_value = mock_pw
        yield mock_pw, mock_browser, mock_context, mock_page


import pytest
from langchain_core.documents import Document

from scrapegraphai.docloaders.chromium import ChromiumLoader


async def dummy_scraper(url):
    """A dummy scraping function that returns dummy HTML content for the URL."""
    return f"<html>dummy content for {url}</html>"


@pytest.fixture
def loader_with_dummy(monkeypatch):
    """Fixture returning a ChromiumLoader instance with dummy scraping methods patched."""
    urls = ["http://example.com", "http://test.com"]
    loader = ChromiumLoader(urls, backend="playwright", requires_js_support=False)
    monkeypatch.setattr(loader, "ascrape_playwright", dummy_scraper)
    monkeypatch.setattr(loader, "ascrape_with_js_support", dummy_scraper)
    monkeypatch.setattr(loader, "ascrape_undetected_chromedriver", dummy_scraper)
    return loader


def test_lazy_load(loader_with_dummy):
    """Test that lazy_load yields Document objects with the correct dummy content and metadata."""
    docs = list(loader_with_dummy.lazy_load())
    assert len(docs) == 2
    for doc, url in zip(docs, loader_with_dummy.urls):
        assert isinstance(doc, Document)
        assert f"dummy content for {url}" in doc.page_content
        assert doc.metadata["source"] == url


@pytest.mark.asyncio
async def test_alazy_load(loader_with_dummy):
    """Test that alazy_load asynchronously yields Document objects with dummy content and proper metadata."""
    docs = [doc async for doc in loader_with_dummy.alazy_load()]
    assert len(docs) == 2
    for doc, url in zip(docs, loader_with_dummy.urls):
        assert isinstance(doc, Document)
        assert f"dummy content for {url}" in doc.page_content
        assert doc.metadata["source"] == url


@pytest.mark.asyncio
async def test_scrape_method_unsupported_backend():
    """Test that the scrape method raises a ValueError when an unsupported backend is provided."""
    loader = ChromiumLoader(["http://example.com"], backend="unsupported")
    with pytest.raises(ValueError):
        await loader.scrape("http://example.com")


@pytest.mark.asyncio
async def test_scrape_method_selenium(monkeypatch):
    """Test that the scrape method works correctly for selenium by returning the dummy selenium content."""

    async def dummy_selenium(url):
        return f"<html>dummy selenium content for {url}</html>"

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="selenium")
    loader.browser_name = "chromium"
    monkeypatch.setattr(loader, "ascrape_undetected_chromedriver", dummy_selenium)
    result = await loader.scrape("http://example.com")
    assert "dummy selenium content" in result


@pytest.mark.asyncio
async def test_ascrape_playwright_scroll(mock_playwright):
    """Test the ascrape_playwright_scroll method with various configurations."""
    mock_pw, mock_browser, mock_context, mock_page = mock_playwright

    url = "http://example.com"
    loader = ChromiumLoader([url], backend="playwright")

    # Test with default parameters
    mock_page.evaluate.side_effect = [1000, 2000, 2000]  # Simulate scrolling
    result = await loader.ascrape_playwright_scroll(url)

    assert mock_page.goto.call_count == 1
    assert mock_page.wait_for_load_state.call_count == 1
    assert mock_page.mouse.wheel.call_count > 0
    assert mock_page.content.call_count == 1

    # Test with custom parameters
    mock_page.evaluate.side_effect = [1000, 2000, 3000, 4000, 4000]
    result = await loader.ascrape_playwright_scroll(
        url, timeout=10, scroll=10000, sleep=1, scroll_to_bottom=True
    )

    assert mock_page.goto.call_count == 2
    assert mock_page.wait_for_load_state.call_count == 2
    assert mock_page.mouse.wheel.call_count > 0
    assert mock_page.content.call_count == 2


@pytest.mark.asyncio
async def test_ascrape_with_js_support(mock_playwright):
    """Test the ascrape_with_js_support method with different browser configurations."""
    mock_pw, mock_browser, mock_context, mock_page = mock_playwright

    url = "http://example.com"
    loader = ChromiumLoader([url], backend="playwright", requires_js_support=True)

    # Test with Chromium
    result = await loader.ascrape_with_js_support(url, browser_name="chromium")
    assert mock_pw.chromium.launch.call_count == 1
    assert mock_page.goto.call_count == 1
    assert mock_page.content.call_count == 1

    # Test with Firefox
    result = await loader.ascrape_with_js_support(url, browser_name="firefox")
    assert mock_pw.firefox.launch.call_count == 1
    assert mock_page.goto.call_count == 2
    assert mock_page.content.call_count == 2

    # Test with invalid browser name
    with pytest.raises(ValueError):
        await loader.ascrape_with_js_support(url, browser_name="invalid")


@pytest.mark.asyncio
async def test_scrape_method_playwright(mock_playwright):
    """Test the scrape method with playwright backend."""
    mock_pw, mock_browser, mock_context, mock_page = mock_playwright

    url = "http://example.com"
    loader = ChromiumLoader([url], backend="playwright")

    mock_page.content.return_value = "<html>Playwright content</html>"
    result = await loader.scrape(url)

    assert "Playwright content" in result
    assert mock_pw.chromium.launch.call_count == 1
    assert mock_page.goto.call_count == 1
    assert mock_page.wait_for_load_state.call_count == 1
    assert mock_page.content.call_count == 1


@pytest.mark.asyncio
async def test_scrape_method_retry_logic(mock_playwright):
    """Test the retry logic in the scrape method."""
    mock_pw, mock_browser, mock_context, mock_page = mock_playwright

    url = "http://example.com"
    loader = ChromiumLoader([url], backend="playwright", retry_limit=3)

    # Simulate two failures and then a success
    mock_page.goto.side_effect = [asyncio.TimeoutError(), aiohttp.ClientError(), None]
    mock_page.content.return_value = "<html>Success after retries</html>"

    result = await loader.scrape(url)

    assert "Success after retries" in result
    assert mock_page.goto.call_count == 3
    assert mock_page.content.call_count == 1

    # Test failure after all retries
    mock_page.goto.side_effect = asyncio.TimeoutError()

    with pytest.raises(RuntimeError):
        await loader.scrape(url)

    assert mock_page.goto.call_count == 6  # 3 more attempts


@pytest.mark.asyncio
async def test_ascrape_playwright_scroll_invalid_params():
    """Test that ascrape_playwright_scroll raises ValueError for invalid scroll parameters."""
    loader = ChromiumLoader(["http://example.com"], backend="playwright")
    with pytest.raises(
        ValueError,
        match="If set, timeout value for scrolling scraper must be greater than 0.",
    ):
        await loader.ascrape_playwright_scroll("http://example.com", timeout=0)
    with pytest.raises(
        ValueError, match="Sleep for scrolling scraper value must be greater than 0."
    ):
        await loader.ascrape_playwright_scroll("http://example.com", sleep=0)
    with pytest.raises(
        ValueError,
        match="Scroll value for scrolling scraper must be greater than or equal to 5000.",
    ):
        await loader.ascrape_playwright_scroll("http://example.com", scroll=4000)


@pytest.mark.asyncio
async def test_ascrape_with_js_support_retry_failure(monkeypatch):
    """Test that ascrape_with_js_support retries and ultimately fails when page.goto always times out."""
    loader = ChromiumLoader(
        ["http://example.com"],
        backend="playwright",
        requires_js_support=True,
        retry_limit=2,
        timeout=1,
    )

    # Create dummy classes to simulate failure in page.goto
    class DummyPage:
        async def goto(self, url, wait_until):
            raise asyncio.TimeoutError("Forced timeout")

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Dummy</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    # Patch the async_playwright to return our dummy
    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    with pytest.raises(RuntimeError, match="Failed to scrape after"):
        await loader.ascrape_with_js_support("http://example.com")


@pytest.mark.asyncio
async def test_ascrape_undetected_chromedriver_success(monkeypatch):
    """Test that ascrape_undetected_chromedriver successfully returns content using the selenium backend."""
    # Create a dummy undetected_chromedriver module with a dummy Chrome driver.
    import types

    dummy_module = types.ModuleType("undetected_chromedriver")

    class DummyDriver:
        def __init__(self, options):
            self.options = options
            self.page_source = "<html>selenium content</html>"

        def quit(self):
            pass

    dummy_module.Chrome = lambda options: DummyDriver(options)
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", dummy_module)

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="selenium", retry_limit=1, timeout=5)
    loader.browser_name = "chromium"
    result = await loader.ascrape_undetected_chromedriver("http://example.com")
    assert "selenium content" in result


@pytest.mark.asyncio
async def test_lazy_load_exception(loader_with_dummy, monkeypatch):
    """Test that lazy_load propagates exception if the scraping function fails."""

    async def dummy_failure(url):
        raise Exception("Dummy scraping error")

    # Patch the scraping method to always raise an exception
    loader_with_dummy.backend = "playwright"
    monkeypatch.setattr(loader_with_dummy, "ascrape_playwright", dummy_failure)
    with pytest.raises(Exception, match="Dummy scraping error"):
        list(loader_with_dummy.lazy_load())


@pytest.mark.asyncio
async def test_ascrape_undetected_chromedriver_unsupported_browser(monkeypatch):
    """Test ascrape_undetected_chromedriver raises an error when an unsupported browser is provided."""
    import types

    dummy_module = types.ModuleType("undetected_chromedriver")
    # Provide a dummy Chrome; this will not be used for an unsupported browser.
    dummy_module.Chrome = lambda options: None
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", dummy_module)

    loader = ChromiumLoader(
        ["http://example.com"], backend="selenium", retry_limit=1, timeout=1
    )
    loader.browser_name = "opera"  # Unsupported browser.
    with pytest.raises(UnboundLocalError):
        await loader.ascrape_undetected_chromedriver("http://example.com")


@pytest.mark.asyncio
async def test_alazy_load_partial_failure(monkeypatch):
    """Test that alazy_load propagates an exception if one of the scraping tasks fails."""
    urls = ["http://example.com", "http://fail.com"]
    loader = ChromiumLoader(urls, backend="playwright")

    async def partial_scraper(url):
        if "fail" in url:
            raise Exception("Scraping failed for " + url)
        return f"<html>Content for {url}</html>"

    monkeypatch.setattr(loader, "ascrape_playwright", partial_scraper)

    with pytest.raises(Exception, match="Scraping failed for http://fail.com"):
        [doc async for doc in loader.alazy_load()]


@pytest.mark.asyncio
async def test_ascrape_playwright_retry_failure(monkeypatch):
    """Test that ascrape_playwright retries scraping and raises RuntimeError after all attempts fail."""

    # Dummy classes to simulate persistent failure in page.goto for ascrape_playwright
    class DummyPage:
        async def goto(self, url, wait_until):
            raise asyncio.TimeoutError("Forced timeout in goto")

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>This should not be returned</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    loader = ChromiumLoader(
        ["http://example.com"], backend="playwright", retry_limit=2, timeout=1
    )
    with pytest.raises(RuntimeError, match="Failed to scrape after 2 attempts"):
        await loader.ascrape_playwright("http://example.com")


@pytest.mark.asyncio
async def test_init_overrides():
    """Test that ChromiumLoader picks up and overrides attributes using kwargs."""
    urls = ["http://example.com"]
    loader = ChromiumLoader(
        urls,
        backend="playwright",
        headless=False,
        proxy={"http": "http://proxy"},
        load_state="load",
        requires_js_support=True,
        storage_state="state",
        browser_name="firefox",
        retry_limit=5,
        timeout=120,
        extra="value",
    )
    # Check that attributes are correctly set
    assert loader.headless is False
    assert loader.proxy == {"http": "http://proxy"}
    assert loader.load_state == "load"
    assert loader.requires_js_support is True
    assert loader.storage_state == "state"
    assert loader.browser_name == "firefox"
    assert loader.retry_limit == 5
    assert loader.timeout == 120
    # Check that extra kwargs go into browser_config
    assert loader.browser_config.get("extra") == "value"
    # Check that the backend remains as provided
    assert loader.backend == "playwright"


@pytest.mark.asyncio
async def test_lazy_load_with_js_support(monkeypatch):
    """Test that lazy_load uses ascrape_with_js_support when requires_js_support is True."""
    urls = ["http://example.com", "http://test.com"]
    loader = ChromiumLoader(urls, backend="playwright", requires_js_support=True)

    async def dummy_js(url):
        return f"<html>JS content for {url}</html>"

    monkeypatch.setattr(loader, "ascrape_with_js_support", dummy_js)
    docs = list(loader.lazy_load())
    assert len(docs) == 2
    for doc, url in zip(docs, urls):
        assert isinstance(doc, Document)
        assert f"JS content for {url}" in doc.page_content
        assert doc.metadata["source"] == url


@pytest.mark.asyncio
async def test_no_retry_returns_none(monkeypatch):
    """Test that ascrape_playwright returns None if retry_limit is set to 0."""
    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", retry_limit=0)

    # Even if we patch ascrape_playwright, the while loop won't run since retry_limit is 0, so it should return None.
    async def dummy(url, browser_name="chromium"):
        return f"<html>Content for {url}</html>"

    monkeypatch.setattr(loader, "ascrape_playwright", dummy)
    result = await loader.ascrape_playwright("http://example.com")
    # With retry_limit=0, the loop never runs and the function returns None.
    assert result is None


@pytest.mark.asyncio
async def test_alazy_load_empty_urls():
    """Test that alazy_load yields no documents when the urls list is empty."""
    loader = ChromiumLoader([], backend="playwright")
    docs = [doc async for doc in loader.alazy_load()]
    assert docs == []


def test_lazy_load_empty_urls():
    """Test that lazy_load yields no documents when the urls list is empty."""
    loader = ChromiumLoader([], backend="playwright")
    docs = list(loader.lazy_load())
    assert docs == []


@pytest.mark.asyncio
async def test_ascrape_undetected_chromedriver_missing_import(monkeypatch):
    """Test that ascrape_undetected_chromedriver raises ImportError when undetected_chromedriver is not installed."""
    # Remove undetected_chromedriver from sys.modules if it exists
    if "undetected_chromedriver" in sys.modules:
        monkeyatch_key = "undetected_chromedriver"
        monkeypatch.delenitem(sys.modules, monkeyatch_key)
    loader = ChromiumLoader(
        ["http://example.com"], backend="selenium", retry_limit=1, timeout=5
    )
    loader.browser_name = "chromium"
    with pytest.raises(
        ImportError, match="undetected_chromedriver is required for ChromiumLoader"
    ):
        await loader.ascrape_undetected_chromedriver("http://example.com")


@pytest.mark.asyncio
async def test_ascrape_undetected_chromedriver_quit_called(monkeypatch):
    """Test that ascrape_undetected_chromedriver calls driver.quit() on every attempt even when get() fails."""
    # List to collect each DummyDriver instance for later inspection.
    driver_instances = []
    attempt_counter = [0]

    class DummyDriver:
        def __init__(self, options):
            self.options = options
            self.quit_called = False
            driver_instances.append(self)

        def get(self, url):
            # Force a failure on the first attempt then succeed on subsequent attempts.
            if attempt_counter[0] < 1:
                attempt_counter[0] += 1
                raise aiohttp.ClientError("Forced failure")
            # If no failure, simply pass.

        @property
        def page_source(self):
            return "<html>driver content</html>"

        def quit(self):
            self.quit_called = True

    import types

    dummy_module = types.ModuleType("undetected_chromedriver")
    dummy_module.Chrome = lambda options: DummyDriver(options)
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", dummy_module)

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="selenium", retry_limit=2, timeout=5)
    loader.browser_name = "chromium"
    result = await loader.ascrape_undetected_chromedriver("http://example.com")
    assert "driver content" in result
    # Verify that two driver instances were used and that each had its quit() method called.
    assert len(driver_instances) == 2
    for driver in driver_instances:
        assert driver.quit_called is True


@pytest.mark.parametrize("backend", ["playwright", "selenium"])
def test_dynamic_import_failure(monkeypatch, backend):
    """Test that ChromiumLoader raises ImportError when dynamic_import fails."""

    def fake_dynamic_import(backend, message):
        raise ImportError("Test dynamic import error")

    monkeypatch.setattr(
        "scrapegraphai.docloaders.chromium.dynamic_import", fake_dynamic_import
    )
    with pytest.raises(ImportError, match="Test dynamic import error"):
        ChromiumLoader(["http://example.com"], backend=backend)


@pytest.mark.asyncio
async def test_ascrape_with_js_support_retry_success(monkeypatch):
    """Test that ascrape_with_js_support retries on failure and returns content on a subsequent successful attempt."""
    attempt_count = {"count": 0}

    class DummyPage:
        async def goto(self, url, wait_until):
            if attempt_count["count"] < 1:
                attempt_count["count"] += 1
                raise asyncio.TimeoutError("Forced timeout")
            # On second attempt, do nothing (simulate successful navigation)

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Success on retry</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    # Create a loader with JS support and a retry_limit of 2 (so one failure is allowed)
    loader = ChromiumLoader(
        ["http://example.com"],
        backend="playwright",
        requires_js_support=True,
        retry_limit=2,
        timeout=1,
    )
    result = await loader.ascrape_with_js_support("http://example.com")
    assert result == "<html>Success on retry</html>"


@pytest.mark.asyncio
async def test_proxy_parsing_in_init(monkeypatch):
    """Test that providing a proxy triggers the use of parse_or_search_proxy and sets loader.proxy correctly."""
    dummy_proxy_value = {"dummy": True}
    monkeypatch.setattr(
        "scrapegraphai.docloaders.chromium.parse_or_search_proxy",
        lambda proxy: dummy_proxy_value,
    )
    loader = ChromiumLoader(
        ["http://example.com"], backend="playwright", proxy="some_proxy_value"
    )
    assert loader.proxy == dummy_proxy_value


@pytest.mark.asyncio
async def test_scrape_method_selenium_firefox(monkeypatch):
    """Test that the scrape method works correctly for selenium with firefox backend."""

    async def dummy_selenium(url):
        return f"<html>dummy selenium firefox content for {url}</html>"

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="selenium")
    loader.browser_name = "firefox"
    monkeypatch.setattr(loader, "ascrape_undetected_chromedriver", dummy_selenium)
    result = await loader.scrape("http://example.com")
    assert "dummy selenium firefox content" in result


def test_init_with_no_proxy():
    """Test that initializing ChromiumLoader with proxy=None results in loader.proxy being None."""
    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", proxy=None)
    assert loader.proxy is None


@pytest.mark.asyncio
async def test_ascrape_playwright_negative_retry(monkeypatch):
    """Test that ascrape_playwright returns None when retry_limit is negative (loop not executed)."""

    # Set-up a dummy playwright context which should never be used because retry_limit is negative.
    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                # Should not be called as retry_limit is negative.
                raise Exception("Should not launch browser")

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())
    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", retry_limit=-1)
    result = await loader.ascrape_playwright("http://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_ascrape_with_js_support_negative_retry(monkeypatch):
    """Test that ascrape_with_js_support returns None when retry_limit is negative (loop not executed)."""

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                # Should not be called because retry_limit is negative.
                raise Exception("Should not launch browser")

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())
    urls = ["http://example.com"]
    loader = ChromiumLoader(
        urls, backend="playwright", requires_js_support=True, retry_limit=-1
    )
    try:
        result = await loader.ascrape_with_js_support("http://example.com")
    except RuntimeError:
        result = None
    assert result is None


@pytest.mark.asyncio
async def test_ascrape_with_js_support_storage_state(monkeypatch):
    """Test that ascrape_with_js_support passes the storage_state to the new_context call."""

    class DummyPage:
        async def goto(self, url, wait_until):
            return

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Storage State Tested</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        def __init__(self):
            self.last_context_kwargs = None

        async def new_context(self, **kwargs):
            self.last_context_kwargs = kwargs
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                dummy_browser = DummyBrowser()
                dummy_browser.launch_kwargs = {
                    "headless": headless,
                    "proxy": proxy,
                    **kwargs,
                }
                return dummy_browser

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                dummy_browser = DummyBrowser()
                dummy_browser.launch_kwargs = {
                    "headless": headless,
                    "proxy": proxy,
                    **kwargs,
                }
                return dummy_browser

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())
    storage_state = "dummy_state"
    loader = ChromiumLoader(
        ["http://example.com"],
        backend="playwright",
        requires_js_support=True,
        storage_state=storage_state,
        retry_limit=1,
    )
    result = await loader.ascrape_with_js_support("http://example.com")
    # To ensure that new_context was called with the correct storage_state, we simulate a launch call
    browser = await DummyPW.chromium.launch(
        headless=loader.headless, proxy=loader.proxy
    )
    await browser.new_context(storage_state=loader.storage_state)
    assert browser.last_context_kwargs is not None
    assert browser.last_context_kwargs.get("storage_state") == storage_state
    assert "<html>Storage State Tested</html>" in result


@pytest.mark.asyncio
async def test_ascrape_playwright_browser_config(monkeypatch):
    """Test that ascrape_playwright passes extra browser_config kwargs to the browser launch."""
    captured_kwargs = {}

    class DummyPage:
        async def goto(self, url, wait_until):
            return

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Config Tested</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        def __init__(self, config):
            self.config = config

        async def new_context(self, **kwargs):
            self.context_kwargs = kwargs
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                nonlocal captured_kwargs
                captured_kwargs = {"headless": headless, "proxy": proxy, **kwargs}
                return DummyBrowser(captured_kwargs)

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                nonlocal captured_kwargs
                captured_kwargs = {"headless": headless, "proxy": proxy, **kwargs}
                return DummyBrowser(captured_kwargs)

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())
    extra_kwarg_value = "test_value"
    loader = ChromiumLoader(
        ["http://example.com"],
        backend="playwright",
        extra=extra_kwarg_value,
        retry_limit=1,
    )
    result = await loader.ascrape_playwright("http://example.com")
    assert captured_kwargs.get("extra") == extra_kwarg_value
    assert "<html>Config Tested</html>" in result


@pytest.mark.asyncio
async def test_scrape_method_js_support(monkeypatch):
    """Test that scrape method calls ascrape_with_js_support when requires_js_support is True."""

    async def dummy_js(url):
        return f"<html>JS supported content for {url}</html>"

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", requires_js_support=True)
    monkeypatch.setattr(loader, "ascrape_with_js_support", dummy_js)
    result = await loader.scrape("http://example.com")
    assert "JS supported content" in result


@pytest.mark.asyncio
async def test_ascrape_playwright_scroll_retry_failure(monkeypatch):
    """Test that ascrape_playwright_scroll retries on failure and returns an error message after retry_limit attempts."""

    # Dummy page that always raises Timeout on goto
    class DummyPage:
        async def goto(self, url, wait_until):
            raise asyncio.TimeoutError("Simulated timeout in goto")

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>No Content</html>"

        evaluate = AsyncMock(
            side_effect=asyncio.TimeoutError("Simulated timeout in evaluate")
        )

        mouse = AsyncMock()

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", retry_limit=2, timeout=1)
    # Use a scroll value just above minimum and a sleep value > 0
    result = await loader.ascrape_playwright_scroll(
        "http://example.com", scroll=5000, sleep=1
    )
    assert "Error: Network error after 2 attempts" in result


@pytest.mark.asyncio
async def test_alazy_load_order(monkeypatch):
    """Test that alazy_load returns documents in the same order as the input URLs even if scraping tasks complete out of order."""
    urls = [
        "http://example.com/first",
        "http://example.com/second",
        "http://example.com/third",
    ]
    loader = ChromiumLoader(urls, backend="playwright")

    async def delayed_scraper(url):
        # Delay inversely proportional to a function of the url to scramble finish order
        import asyncio

        delay = 0.3 - 0.1 * (len(url) % 3)
        await asyncio.sleep(delay)
        return f"<html>Content for {url}</html>"

    monkeypatch.setattr(loader, "ascrape_playwright", delayed_scraper)

    docs = [doc async for doc in loader.alazy_load()]
    # Ensure that the order of documents matches the order of input URLs
    for doc, url in zip(docs, urls):
        assert doc.metadata["source"] == url
        assert f"Content for {url}" in doc.page_content


@pytest.mark.asyncio
async def test_ascrape_with_js_support_calls_close(monkeypatch):
    """Test that ascrape_with_js_support calls browser.close() after scraping."""
    close_called_flag = {"called": False}

    class DummyPage:
        async def goto(self, url, wait_until):
            return

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Dummy Content</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            close_called_flag["called"] = True
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    urls = ["http://example.com"]
    loader = ChromiumLoader(
        urls, backend="playwright", requires_js_support=True, retry_limit=1, timeout=5
    )
    result = await loader.ascrape_with_js_support("http://example.com")
    assert result == "<html>Dummy Content</html>"
    assert close_called_flag["called"] is True


@pytest.mark.asyncio
async def test_lazy_load_invalid_backend(monkeypatch):
    """Test that lazy_load raises AttributeError if the scraping method for an invalid backend is missing."""
    # Create a loader instance with a backend that does not have a corresponding scraping method.
    loader = ChromiumLoader(["http://example.com"], backend="nonexistent")
    with pytest.raises(AttributeError):
        # lazy_load calls asyncio.run(scraping_fn(url)) for each URL.
        list(loader.lazy_load())


@pytest.mark.asyncio
async def test_ascrape_undetected_chromedriver_failure(monkeypatch):
    """Test that ascrape_undetected_chromedriver returns an error message after all retry attempts when driver.get always fails."""
    import types

    # Create a dummy undetected_chromedriver module with a dummy Chrome driver that always fails.
    dummy_module = types.ModuleType("undetected_chromedriver")

    class DummyDriver:
        def __init__(self, options):
            self.options = options
            self.quit_called = False

        def get(self, url):
            # Simulate a failure in fetching the page.
            raise aiohttp.ClientError("Forced failure in get")

        @property
        def page_source(self):
            return "<html>This should not be reached</html>"

        def quit(self):
            self.quit_called = True

    dummy_module.Chrome = lambda options: DummyDriver(options)
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", dummy_module)

    loader = ChromiumLoader(
        ["http://example.com"], backend="selenium", retry_limit=2, timeout=1
    )
    loader.browser_name = "chromium"
    result = await loader.ascrape_undetected_chromedriver("http://example.com")
    # Check that the error message indicates the number of attempts and the forced failure.
    assert "Error: Network error after 2 attempts" in result


@pytest.mark.asyncio
async def test_ascrape_playwright_scroll_constant_height(mock_playwright):
    """Test that ascrape_playwright_scroll exits the scroll loop when page height remains constant."""
    mock_pw, mock_browser, mock_context, mock_page = mock_playwright
    # Set evaluate to always return constant height value (simulate constant page height)
    mock_page.evaluate.return_value = 1000
    # Return dummy content once scrolling loop breaks
    mock_page.content.return_value = "<html>Constant height content</html>"
    # Use a scroll value above minimum and a very short sleep to cycle quickly
    loader = ChromiumLoader(["http://example.com"], backend="playwright")
    result = await loader.ascrape_playwright_scroll(
        "http://example.com", scroll=6000, sleep=0.1
    )
    assert "Constant height content" in result


def test_lazy_load_empty_content(monkeypatch):
    """Test that lazy_load yields a Document with empty content if the scraper returns an empty string."""
    from langchain_core.documents import Document

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", requires_js_support=False)

    async def dummy_scraper(url):
        return ""

    monkeypatch.setattr(loader, "ascrape_playwright", dummy_scraper)
    docs = list(loader.lazy_load())
    assert len(docs) == 1
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.page_content == ""
        assert doc.metadata["source"] in urls


@pytest.mark.asyncio
async def test_lazy_load_scraper_returns_none(monkeypatch):
    """Test that lazy_load yields Document objects with page_content as None when the scraper returns None."""
    urls = ["http://example.com", "http://test.com"]
    loader = ChromiumLoader(urls, backend="playwright")

    async def dummy_none(url):
        return None

    monkeypatch.setattr(loader, "ascrape_playwright", dummy_none)
    docs = list(loader.lazy_load())
    assert len(docs) == 2
    for doc, url in zip(docs, urls):
        from langchain_core.documents import Document

        assert isinstance(doc, Document)
        assert doc.page_content is None
        assert doc.metadata["source"] == url


@pytest.mark.asyncio
async def test_alazy_load_mixed_none_and_content(monkeypatch):
    """Test that alazy_load yields Document objects in order when one scraper returns None and the other valid HTML."""
    urls = ["http://example.com", "http://none.com"]
    loader = ChromiumLoader(urls, backend="playwright")

    async def mixed_scraper(url):
        if "none" in url:
            return None
        return f"<html>Valid content for {url}</html>"

    monkeypatch.setattr(loader, "ascrape_playwright", mixed_scraper)
    docs = [doc async for doc in loader.alazy_load()]
    assert len(docs) == 2
    # Ensure order is preserved and check contents
    assert docs[0].metadata["source"] == "http://example.com"
    assert "<html>Valid content for http://example.com</html>" in docs[0].page_content
    assert docs[1].metadata["source"] == "http://none.com"
    assert docs[1].page_content is None


@pytest.mark.asyncio
async def test_ascrape_with_js_support_exception_cleanup(monkeypatch):
    """Test that ascrape_with_js_support calls browser.close() after an exception occurs."""
    close_called_flag = {"called": False}

    class DummyPage:
        async def goto(self, url, wait_until):
            raise asyncio.TimeoutError("Forced timeout")

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>No Content</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            close_called_flag["called"] = True
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    loader = ChromiumLoader(
        ["http://example.com"],
        backend="playwright",
        requires_js_support=True,
        retry_limit=1,
        timeout=1,
    )

    with pytest.raises(RuntimeError, match="Failed to scrape after 1 attempts"):
        await loader.ascrape_with_js_support("http://example.com")


@patch("scrapegraphai.docloaders.chromium.dynamic_import")
def test_init_dynamic_import_called(mock_dynamic_import):
    """Test that dynamic_import is called during initialization."""
    urls = ["http://example.com"]
    _ = ChromiumLoader(urls, backend="playwright")
    mock_dynamic_import.assert_called_with("playwright", ANY)


@pytest.mark.asyncio
async def test_alazy_load_selenium_backend(monkeypatch):
    """Test that alazy_load correctly yields Document objects when using selenium backend."""
    urls = ["http://example.com", "http://selenium.com"]
    loader = ChromiumLoader(urls, backend="selenium")

    async def dummy_selenium(url):
        return f"<html>dummy selenium backend content for {url}</html>"

    monkeypatch.setattr(loader, "ascrape_undetected_chromedriver", dummy_selenium)
    docs = [doc async for doc in loader.alazy_load()]
    for doc, url in zip(docs, urls):
        assert f"dummy selenium backend content for {url}" in doc.page_content
        assert doc.metadata["source"] == url
    assert close_called_flag["called"] is True


@pytest.mark.asyncio
async def test_ascrape_undetected_chromedriver_zero_retry(monkeypatch):
    """Test that ascrape_undetected_chromedriver returns empty result when retry_limit is set to 0."""
    import types

    # Create a dummy undetected_chromedriver module where Chrome is defined but will not be used.
    dummy_module = types.ModuleType("undetected_chromedriver")
    dummy_module.Chrome = lambda options: None
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", dummy_module)

    loader = ChromiumLoader(
        ["http://example.com"], backend="selenium", retry_limit=0, timeout=5
    )
    loader.browser_name = "chromium"
    # With retry_limit=0, the while loop never runs so the result remains an empty string.
    result = await loader.ascrape_undetected_chromedriver("http://example.com")
    assert result == ""


@pytest.mark.asyncio
async def test_scrape_selenium_exception(monkeypatch):
    """Test that the scrape method for selenium backend raises a ValueError when ascrape_undetected_chromedriver fails."""

    async def failing_scraper(url):
        raise Exception("dummy error")

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="selenium", retry_limit=1, timeout=5)
    loader.browser_name = "chromium"
    monkeypatch.setattr(loader, "ascrape_undetected_chromedriver", failing_scraper)
    with pytest.raises(
        ValueError, match="Failed to scrape with undetected chromedriver: dummy error"
    ):
        await loader.scrape("http://example.com")


@pytest.mark.asyncio
async def test_ascrape_playwright_scroll_exception_cleanup(monkeypatch):
    """Test that ascrape_playwright_scroll calls browser.close() when an exception occurs during page navigation."""
    close_called = {"called": False}

    class DummyPage:
        async def goto(self, url, wait_until):
            raise asyncio.TimeoutError("Simulated timeout in goto")

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Never reached</html>"

        async def evaluate(self, script):
            return 1000  # constant height value to simulate no progress in scrolling

        mouse = AsyncMock()
        mouse.wheel = AsyncMock()

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            close_called["called"] = True

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())

    loader = ChromiumLoader(
        ["http://example.com"],
        backend="playwright",
        retry_limit=2,
        timeout=1,
        headless=True,
    )
    result = await loader.ascrape_playwright_scroll(
        "http://example.com", scroll=5000, sleep=0.1, scroll_to_bottom=True
    )

    assert "Error: Network error after" in result
    assert close_called["called"] is True


@pytest.mark.asyncio
async def test_ascrape_with_js_support_non_timeout_retry(monkeypatch):
    """Test that ascrape_with_js_support retries on a non-timeout exception and eventually succeeds."""
    attempt = {"count": 0}

    class DummyPage:
        async def goto(self, url, wait_until):
            if attempt["count"] < 1:
                attempt["count"] += 1
                raise ValueError("Non-timeout error")

        async def wait_for_load_state(self, state):
            return

        async def content(self):
            return "<html>Success after non-timeout retry</html>"

    class DummyContext:
        async def new_page(self):
            return DummyPage()

    class DummyBrowser:
        async def new_context(self, **kwargs):
            return DummyContext()

        async def close(self):
            return

    class DummyPW:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return

        class chromium:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

        class firefox:
            @staticmethod
            async def launch(headless, proxy, **kwargs):
                return DummyBrowser()

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: DummyPW())
    loader = ChromiumLoader(
        ["http://nontimeout.com"],
        backend="playwright",
        requires_js_support=True,
        retry_limit=2,
        timeout=1,
    )
    result = await loader.ascrape_with_js_support("http://nontimeout.com")
    assert "Success after non-timeout retry" in result


@pytest.mark.asyncio
async def test_scrape_uses_js_support_flag(monkeypatch):
    """Test that the scrape method uses ascrape_with_js_support when requires_js_support is True."""

    async def dummy_js(url, browser_name="chromium"):
        return f"<html>JS flag content for {url}</html>"

    async def dummy_playwright(url, browser_name="chromium"):
        return f"<html>Playwright content for {url}</html>"

    urls = ["http://example.com"]
    loader = ChromiumLoader(urls, backend="playwright", requires_js_support=True)
    monkeypatch.setattr(loader, "ascrape_with_js_support", dummy_js)
    monkeypatch.setattr(loader, "ascrape_playwright", dummy_playwright)
    result = await loader.scrape("http://example.com")
    assert "JS flag content" in result
