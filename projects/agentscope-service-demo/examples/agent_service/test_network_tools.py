"""Offline contract and public-network boundary tests for web-search MCP."""
import asyncio
import json
import socket
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import network_tools as web


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_wire_format_and_real_sources(self):
        payload = {'content': [
            {'type': 'web_search_tool_result', 'content': [
                {'type': 'web_search_result', 'url': 'https://example.com', 'title': 'Weather'},
                {'type': 'web_search_result', 'url': 'https://example.com', 'title': 'Duplicate'}]},
            {'type': 'text', 'text': 'Do not return generated prose as a source', 'citations': [
                {'url': 'https://example.com', 'cited_text': 'Sunny'}]}]}
        def respond(request):
            self.assertEqual(str(request.url), web.SEARCH_ENDPOINT)
            self.assertEqual(request.headers['x-api-key'], 'test-key')
            body = json.loads(request.content)
            self.assertEqual(body['tools'][0]['type'], 'web_search_20250305')
            self.assertEqual(body['model'], 'deepseek-v4-flash')
            return httpx.Response(200, json=payload)
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(web, 'settings', return_value='test-key'), patch.object(web.httpx, 'AsyncClient', return_value=client):
            result = await web.web_search('weather today')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['snippet'], 'Sunny')
        self.assertNotIn('test-key', json.dumps(result))

    async def test_errors_do_not_return_provider_body_or_key(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(401, text='secret-test-key echoed by provider')))
        with patch.object(web, 'settings', return_value='secret-test-key'), patch.object(web.httpx, 'AsyncClient', return_value=client):
            with self.assertRaisesRegex(ValueError, '401') as error:
                await web.web_search('weather')
        self.assertNotIn('secret-test-key', str(error.exception))

    def test_missing_structured_results_and_provider_failure(self):
        for payload in ({'content': [{'type': 'text', 'text': 'https://fake.test'}]},
                        {'content': [{'type': 'web_search_tool_result', 'content': {'type': 'web_search_tool_result_error'}}]}):
            with self.assertRaises(ValueError):
                web.parse_search(payload, 5)

    async def test_invalid_input(self):
        for query, count in [('', 5), ('x' * 501, 5), ('weather', 11)]:
            with self.assertRaises(ValueError):
                await web.web_search(query, count)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dns_is_pinned_and_private_mixed_answers_rejected(self):
        loop = asyncio.get_running_loop()
        def answer(ip):
            return (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))
        with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=[answer('93.184.216.34')])):
            target, host, sni = await web.public_target('https://example.com/a?q=1')
        self.assertEqual(str(target), 'https://93.184.216.34/a?q=1')
        self.assertEqual(host, 'example.com')
        self.assertEqual(sni, 'example.com')
        for ips in [['127.0.0.1'], ['192.168.0.206'], ['169.254.169.254'], ['93.184.216.34', '10.0.0.1']]:
            with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=[answer(ip) for ip in ips])):
                with self.assertRaises(ValueError):
                    await web.public_target('https://example.com')

    def test_url_and_address_validation(self):
        for url in ['file:///etc/passwd', 'http://user:pass@example.com', 'http://example.com:8000', 'http://example.com\\@evil.test', 'http://example.com/\n']:
            with self.assertRaises(ValueError):
                web.check_url(url)
        for ip in ['::1', '::ffff:127.0.0.1', 'fc00::1', '224.0.0.1', '0.0.0.0']:
            self.assertFalse(web.is_public(ip))

    def test_extract_chinese_and_drop_hidden_content(self):
        raw = '<meta charset="gb2312"><title>武汉天气</title><nav>导航</nav><script>bad()</script><p>晴天 23度</p><div hidden>secret</div><p>正文</p>'.encode('gb18030')
        result = web.extract_page(raw, 'text/html', 1000)
        self.assertEqual(result['title'], '武汉天气')
        self.assertIn('晴天 23度', result['content'])
        for excluded in ['bad()', 'secret', '导航']:
            self.assertNotIn(excluded, result['content'])
        self.assertTrue(web.extract_page(b'x' * 2000, 'text/plain', 1000)['truncated'])

    async def test_redirect_to_private_address_is_blocked(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={'location': 'http://127.0.0.1/admin'})))
        resolver = AsyncMock(side_effect=[(httpx.URL('https://93.184.216.34'), 'example.com', b'example.com'), ValueError('private address')])
        with patch.object(web, 'public_target', resolver), patch.object(web.httpx, 'AsyncClient', return_value=client):
            with self.assertRaisesRegex(ValueError, 'private address'):
                await web.web_fetch('https://example.com')
        self.assertEqual(resolver.call_args.args[0], 'http://127.0.0.1/admin')

    async def test_fetch_content_size_and_media_type(self):
        for content_type, body in [('application/pdf', b'%PDF'), ('text/plain', b'x' * (web.MAX_BYTES + 1))]:
            client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={'content-type': content_type}, content=body)))
            with patch.object(web, 'public_target', AsyncMock(return_value=(httpx.URL('https://93.184.216.34'), 'example.com', b'example.com'))), patch.object(web.httpx, 'AsyncClient', return_value=client):
                with self.assertRaises(ValueError):
                    await web.web_fetch('https://example.com')


if __name__ == '__main__':
    unittest.main()
