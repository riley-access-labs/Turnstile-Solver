import os
import sys
import time
import uuid
import json
import random
import logging
import asyncio
import argparse
from quart import Quart, request, jsonify
from camoufox.async_api import AsyncCamoufox
from patchright.async_api import async_playwright


COLORS = {
    'MAGENTA': '\033[35m',
    'BLUE': '\033[34m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'RED': '\033[31m',
    'RESET': '\033[0m',
}


class CustomLogger(logging.Logger):
    @staticmethod
    def format_message(level, color, message):
        timestamp = time.strftime('%H:%M:%S')
        return f"[{timestamp}] [{COLORS.get(color)}{level}{COLORS.get('RESET')}] -> {message}"

    def debug(self, message, *args, **kwargs):
        super().debug(self.format_message('DEBUG', 'MAGENTA', message), *args, **kwargs)

    def info(self, message, *args, **kwargs):
        super().info(self.format_message('INFO', 'BLUE', message), *args, **kwargs)

    def success(self, message, *args, **kwargs):
        super().info(self.format_message('SUCCESS', 'GREEN', message), *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        super().warning(self.format_message('WARNING', 'YELLOW', message), *args, **kwargs)

    def error(self, message, *args, **kwargs):
        super().error(self.format_message('ERROR', 'RED', message), *args, **kwargs)


logging.setLoggerClass(CustomLogger)
logger = logging.getLogger("TurnstileAPIServer")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
logger.addHandler(handler)


class TurnstileAPIServer:
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Turnstile Solver</title>
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" defer async></script>
        <script>
            async function fetchIP() {
                try {
                    const response = await fetch('https://checkip.amazonaws.com');
                    const ip = (await response.text()).trim();
                    document.getElementById('ip-display').innerText = `Your IP: ${ip}`;
                } catch (error) {
                    console.error('Error fetching IP:', error);
                    document.getElementById('ip-display').innerText = 'Failed to fetch IP';
                }
            }
            window.onload = fetchIP;
            window.turnstileToken = null;
            window.turnstileSuccess = false;
            window.onCaptchaSuccess = function(token) {
                console.log('Turnstile solved successfully:', token);
                window.turnstileToken = token;
                window.turnstileSuccess = true;
            };
        </script>
    </head>
    <body>
        <!-- cf turnstile -->
        <p id="ip-display">Fetching your IP...</p>
    </body>
    </html>
    """

    def __init__(self, headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool):
        self.app = Quart(__name__)
        self.debug = debug
        self.results = self._load_results()
        self.browser_type = browser_type
        self.headless = headless
        self.useragent = useragent
        self.thread_count = thread
        self.proxy_support = proxy_support
        self.browser_pool = asyncio.Queue()
        self.browser_args = []
        if useragent:
            self.browser_args.append(f"--user-agent={useragent}")

        self._setup_routes()

    @staticmethod
    def _load_results():
        """Load previous results from results.json."""
        try:
            if os.path.exists("results.json"):
                with open("results.json", "r") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading results: {str(e)}. Starting with an empty results dictionary.")
        return {}

    def _save_results(self):
        """Save results to results.json."""
        try:
            with open("results.json", "w") as result_file:
                json.dump(self.results, result_file, indent=4)
        except IOError as e:
            logger.error(f"Error saving results to file: {str(e)}")

    def _setup_routes(self) -> None:
        """Set up the application routes."""
        self.app.before_serving(self._startup)
        self.app.route('/turnstile', methods=['GET'])(self.process_turnstile)
        self.app.route('/result', methods=['GET'])(self.get_result)
        self.app.route('/')(self.index)

    async def _startup(self) -> None:
        """Initialize the browser and page pool on startup."""
        logger.info("Starting browser initialization")
        try:
            await self._initialize_browser()
        except Exception as e:
            logger.error(f"Failed to initialize browser: {str(e)}")
            raise

    async def _initialize_browser(self) -> None:
        """Initialize the browser and create the page pool."""

        if self.browser_type in ['chromium', 'chrome', 'msedge']:
            playwright = await async_playwright().start()
        elif self.browser_type == "camoufox":
            headlessMode = 'virtual' if self.headless else False
            camoufox = AsyncCamoufox(headless=headlessMode, geoip=True, humanize=True)

        for _ in range(self.thread_count):
            if self.browser_type in ['chromium', 'chrome', 'msedge']:
                browser = await playwright.chromium.launch(
                    channel=self.browser_type,
                    headless=self.headless,
                    args=self.browser_args
                )

            elif self.browser_type == "camoufox":
                browser = await camoufox.start()

            await self.browser_pool.put((_+1, browser))

            if self.debug:
                logger.success(f"Browser {_ + 1} initialized successfully")

        logger.success(f"Browser pool initialized with {self.browser_pool.qsize()} browsers")


    async def _solve_turnstile(self, task_id: str, url: str, sitekey: str, action: str = None, cdata: str = None, proxy: str = None, useragent: str = None):
        """Solve the Turnstile challenge."""
        used_proxy = None

        index, browser = await self.browser_pool.get()

        # Use proxy from API parameter if provided, otherwise fallback to file-based proxy selection
        if proxy:
            # Proxy provided via API
            used_proxy = proxy
            if self.debug:
                logger.debug(f"Browser {index}: Using API-provided proxy: {proxy}")
        elif self.proxy_support:
            # Fallback to file-based proxy selection
            proxy_file_path = os.path.join(os.getcwd(), "proxies.txt")
            
            try:
                with open(proxy_file_path) as proxy_file:
                    proxies = [line.strip() for line in proxy_file if line.strip()]

                used_proxy = random.choice(proxies) if proxies else None
                if self.debug and used_proxy:
                    logger.debug(f"Browser {index}: Using file-based proxy: {used_proxy}")
            except FileNotFoundError:
                if self.debug:
                    logger.warning(f"Browser {index}: proxies.txt file not found, proceeding without proxy")

        # Determine user agent to use - API parameter takes precedence over global setting
        effective_useragent = useragent or self.useragent
        
        # Configure browser context with proxy and user agent if available
        context_options = {}
        
        if used_proxy:
            # Check for scheme://host:port format first
            if '://' in used_proxy:
                parts = proxy.split(':')
                proxy_scheme, proxy_ip, proxy_port, proxy_user, proxy_pass = parts
                context_options["proxy"] = {"server": f"{proxy_scheme}://{proxy_ip}:{proxy_port}", "username": proxy_user, "password": proxy_pass}
            else:
                parts = used_proxy.split(':')
                if len(parts) == 2:
                    # Format: host:port
                    proxy_host, proxy_port = parts
                    context_options["proxy"] = {"server": f"http://{proxy_host}:{proxy_port}"}
                elif len(parts) == 3:
                    # Format: host:port:scheme
                    proxy_host, proxy_port, proxy_scheme = parts
                    context_options["proxy"] = {"server": f"{proxy_scheme}://{proxy_host}:{proxy_port}"}
                elif len(parts) >= 4:
                    # Format: host:port:username:password (username/password may contain colons)
                    proxy_host = parts[0]
                    proxy_port = parts[1]
                    
                    # Join the remaining parts and split on the last colon to separate username and password
                    remaining = ':'.join(parts[2:])
                    if ':' in remaining:
                        # Find the last colon to separate username and password
                        last_colon_idx = remaining.rfind(':')
                        proxy_user = remaining[:last_colon_idx]
                        proxy_pass = remaining[last_colon_idx + 1:]
                    else:
                        # No password, only username
                        proxy_user = remaining
                        proxy_pass = ""
                    
                    context_options["proxy"] = {
                        "server": f"http://{proxy_host}:{proxy_port}", 
                        "username": proxy_user, 
                        "password": proxy_pass
                    }
                else:
                    logger.error(f"Browser {index}: Invalid proxy format: {used_proxy}")
        
        if effective_useragent:
            context_options["user_agent"] = effective_useragent
            if self.debug:
                logger.debug(f"Browser {index}: Using user agent: {effective_useragent}")
        
        context = await browser.new_context(**context_options)

        page = await context.new_page()

        start_time = time.time()

        try:
            if self.debug:
                logger.debug(f"Browser {index}: Starting Turnstile solve for URL: {url} with Sitekey: {sitekey} | Proxy: {used_proxy}")
                logger.debug(f"Browser {index}: Setting up page data and route")

            url_with_slash = url + "/" if not url.endswith("/") else url
            turnstile_div = f'<div class="cf-turnstile" data-sitekey="{sitekey}" data-callback="onCaptchaSuccess"' + (f' data-action="{action}"' if action else '') + (f' data-cdata="{cdata}"' if cdata else '') + '></div>'
            page_data = self.HTML_TEMPLATE.replace("<!-- cf turnstile -->", turnstile_div)

            await page.route(url_with_slash, lambda route: route.fulfill(body=page_data, status=200))
            await page.goto(url_with_slash)

            if self.debug:
                logger.debug(f"Browser {index}: Waiting for DOM Content Loaded")
            await page.wait_for_load_state("domcontentloaded")
            if self.debug:
                logger.debug(f"Browser {index}: Waiting for network idle")
            await page.wait_for_load_state("networkidle")

            if self.debug:
                logger.debug(f"Browser {index}: Setting up Turnstile widget dimensions")

            await page.eval_on_selector("//div[@class='cf-turnstile']", "el => el.style.width = '70px'")

            if self.debug:
                logger.debug(f"Browser {index}: Starting Turnstile response retrieval loop")

            for _ in range(20):
                try:
                    turnstile_check = await page.input_value("[name=cf-turnstile-response]", timeout=2000)
                    if turnstile_check == "":
                        if self.debug:
                            logger.debug(f"Browser {index}: Attempt {_} - No Turnstile response yet")
                        
                        await page.locator("//div[@class='cf-turnstile']").click(timeout=1000)
                        await asyncio.sleep(0.5)
                    else:
                        elapsed_time = round(time.time() - start_time, 3)

                        logger.success(f"Browser {index}: Successfully solved captcha - {COLORS.get('MAGENTA')}{turnstile_check[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")

                        self.results[task_id] = {"value": turnstile_check, "elapsed_time": elapsed_time}
                        self._save_results()
                        break
                except:
                    pass

            # Fallback check using window.turnstileToken if primary method didn't find token
            if self.results.get(task_id) == "CAPTCHA_NOT_READY":
                try:
                    if self.debug:
                        logger.debug(f"Browser {index}: Attempting fallback using window.turnstileToken")
                    
                    window_token = await page.evaluate("window.turnstileToken")
                    if window_token and window_token != "":
                        elapsed_time = round(time.time() - start_time, 3)
                        
                        logger.success(f"Browser {index}: Successfully solved captcha via fallback - {COLORS.get('MAGENTA')}{window_token[:10]}{COLORS.get('RESET')} in {COLORS.get('GREEN')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                        
                        self.results[task_id] = {"value": window_token, "elapsed_time": elapsed_time}
                        self._save_results()
                    else:
                        elapsed_time = round(time.time() - start_time, 3)
                        self.results[task_id] = {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time}
                        if self.debug:
                            logger.error(f"Browser {index}: Error solving Turnstile in {COLORS.get('RED')}{elapsed_time}{COLORS.get('RESET')} Seconds")
                except Exception as e:
                    elapsed_time = round(time.time() - start_time, 3)
                    self.results[task_id] = {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time}
                    if self.debug:
                        logger.error(f"Browser {index}: Error in fallback check: {str(e)}")

        except Exception as e:
            elapsed_time = round(time.time() - start_time, 3)
            self.results[task_id] = {"value": "CAPTCHA_FAIL", "elapsed_time": elapsed_time}
            if self.debug:
                logger.error(f"Browser {index}: Error solving Turnstile: {str(e)}")
        finally:
            if self.debug:
                logger.debug(f"Browser {index}: Clearing page state")

            await context.close()
            await self.browser_pool.put((index, browser))

    async def process_turnstile(self):
        """Handle the /turnstile endpoint requests."""
        url = request.args.get('url')
        sitekey = request.args.get('sitekey')
        action = request.args.get('action')
        cdata = request.args.get('cdata')
        proxy = request.args.get('proxy')
        useragent = request.args.get('useragent')

        if not url or not sitekey:
            return jsonify({
                "status": "error",
                "error": "Both 'url' and 'sitekey' are required"
            }), 400

        task_id = str(uuid.uuid4())
        self.results[task_id] = "CAPTCHA_NOT_READY"

        try:
            asyncio.create_task(self._solve_turnstile(task_id=task_id, url=url, sitekey=sitekey, action=action, cdata=cdata, proxy=proxy, useragent=useragent))

            if self.debug:
                logger.debug(f"Request completed with taskid {task_id}.")
            return jsonify({"task_id": task_id}), 202
        except Exception as e:
            logger.error(f"Unexpected error processing request: {str(e)}")
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500

    async def get_result(self):
        """Return solved data"""
        task_id = request.args.get('id')

        if not task_id or task_id not in self.results:
            return jsonify({"status": "error", "error": "Invalid task ID/Request parameter"}), 400

        result = self.results[task_id]
        status_code = 200

        if "CAPTCHA_FAIL" in result:
            status_code = 422

        return result, status_code

    @staticmethod
    async def index():
        """Serve the API documentation page."""
        return """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Turnstile Solver API</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-gray-900 text-gray-200 min-h-screen flex items-center justify-center">
                <div class="bg-gray-800 p-8 rounded-lg shadow-md max-w-2xl w-full border border-red-500">
                    <h1 class="text-3xl font-bold mb-6 text-center text-red-500">Welcome to Turnstile Solver API</h1>

                    <p class="mb-4 text-gray-300">To use the turnstile service, send a GET request to 
                       <code class="bg-red-700 text-white px-2 py-1 rounded">/turnstile</code> with the following query parameters:</p>

                    <ul class="list-disc pl-6 mb-6 text-gray-300">
                        <li><strong>url</strong> (required): The URL where Turnstile is to be validated</li>
                        <li><strong>sitekey</strong> (required): The site key for Turnstile</li>
                        <li><strong>action</strong> (optional): Action parameter for Turnstile</li>
                        <li><strong>cdata</strong> (optional): Custom data parameter for Turnstile</li>
                        <li><strong>proxy</strong> (optional): Proxy to use for the request</li>
                        <li><strong>useragent</strong> (optional): Custom User-Agent string for the browser</li>
                    </ul>

                    <div class="bg-gray-700 p-4 rounded-lg mb-6 border border-red-500">
                        <p class="font-semibold mb-2 text-red-400">Example usage:</p>
                        <code class="text-sm break-all text-red-300">/turnstile?url=https://example.com&sitekey=sitekey</code>
                        <br><br>
                        <p class="font-semibold mb-2 text-red-400">With proxy:</p>
                        <code class="text-sm break-all text-red-300">/turnstile?url=https://example.com&sitekey=sitekey&proxy=127.0.0.1:8080</code>
                        <br><br>
                        <p class="font-semibold mb-2 text-red-400">With custom user agent:</p>
                        <code class="text-sm break-all text-red-300">/turnstile?url=https://example.com&sitekey=sitekey&useragent=Mozilla/5.0...</code>
                        <br><br>
                        <p class="font-semibold mb-2 text-red-400">Proxy formats supported:</p>
                        <ul class="text-xs text-red-300 mt-2 space-y-1">
                            <li>• host:port (e.g., 127.0.0.1:8080)</li>
                            <li>• scheme://host:port (e.g., http://127.0.0.1:8080)</li>
                            <li>• host:port:scheme (e.g., 127.0.0.1:8080:http)</li>
                            <li>• host:port:username:password (e.g., 127.0.0.1:8080:user:pass)</li>
                            <li>• scheme:host:port:username:password (e.g., http:127.0.0.1:8080:user:pass)</li>
                        </ul>
                    </div>

                    <div class="bg-red-900 border-l-4 border-red-600 p-4 mb-6">
                        <p class="text-red-200 font-semibold">This project is inspired by 
                           <a href="https://github.com/Body-Alhoha/turnaround" class="text-red-300 hover:underline">Turnaround</a> 
                           and is currently maintained by 
                           <a href="https://github.com/Theyka" class="text-red-300 hover:underline">Theyka</a> 
                           and <a href="https://github.com/sexfrance" class="text-red-300 hover:underline">Sexfrance</a>.</p>
                    </div>
                </div>
            </body>
            </html>
        """


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Turnstile API Server")

    parser.add_argument('--headless', type=bool, default=False, help='Run the browser in headless mode, without opening a graphical interface. This option requires the --useragent argument to be set (default: False)')
    parser.add_argument('--useragent', type=str, default=None, help='Specify a custom User-Agent string for the browser. If not provided, the default User-Agent is used')
    parser.add_argument('--debug', type=bool, default=False, help='Enable or disable debug mode for additional logging and troubleshooting information (default: False)')
    parser.add_argument('--browser_type', type=str, default='chromium', help='Specify the browser type for the solver. Supported options: chromium, chrome, msedge, camoufox (default: chromium)')
    parser.add_argument('--thread', type=int, default=1, help='Set the number of browser threads to use for multi-threaded mode. Increasing this will speed up execution but requires more resources (default: 1)')
    parser.add_argument('--proxy', type=bool, default=False, help='Enable proxy support for the solver (Default: False)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Specify the IP address where the API solver runs. (Default: 127.0.0.1)')
    parser.add_argument('--port', type=str, default='5000', help='Set the port for the API solver to listen on. (Default: 5000)')
    return parser.parse_args()


def create_app(headless: bool, useragent: str, debug: bool, browser_type: str, thread: int, proxy_support: bool) -> Quart:
    server = TurnstileAPIServer(headless=headless, useragent=useragent, debug=debug, browser_type=browser_type, thread=thread, proxy_support=proxy_support)
    return server.app



if __name__ == '__main__':
    args = parse_args()
    browser_types = [
        'chromium',
        'chrome',
        'msedge',
        'camoufox',
    ]
    if args.browser_type not in browser_types:
        logger.error(f"Unknown browser type: {COLORS.get('RED')}{args.browser_type}{COLORS.get('RESET')} Available browser types: {browser_types}")
    else:
        app = create_app(headless=args.headless, debug=args.debug, useragent=args.useragent, browser_type=args.browser_type, thread=args.thread, proxy_support=args.proxy)
        app.run(host=args.host, port=int(args.port))
