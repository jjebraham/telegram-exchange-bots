import json
import unittest
from urllib.error import HTTPError, URLError

from runpod_api_client import ActionOutcomeUnknown, RunpodAPI, RunpodAPIError


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, maximum): return self.data


class Opener:
    def __init__(self, result): self.result, self.requests = result, []
    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.result, Exception): raise self.result
        return Response(self.result)


class APITests(unittest.TestCase):
    def test_status_get_and_allowed_action(self):
        opener = Opener(json.dumps({'id': 'pod-1', 'status': 'RUNNING', 'env': {'SECRET': 'secret'}}).encode())
        api = RunpodAPI('api-key', opener=opener)
        self.assertEqual(api.status('pod-1')['status'], 'RUNNING')
        self.assertEqual(opener.requests[-1].get_method(), 'GET')
        api.transition('pod-1', 'stop')
        request = opener.requests[-1]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), {'action': 'stop'})
        self.assertEqual(request.full_url, 'https://api.runpod.io/v2/pods/pod-1/action')

    def test_no_unsupported_action_and_no_host_injection(self):
        opener = Opener(b'{}')
        api = RunpodAPI('api-key', opener=opener)
        with self.assertRaises(RunpodAPIError): api.transition('pod-1', 'terminate')
        with self.assertRaises(RunpodAPIError): api.status('../other')
        self.assertEqual(opener.requests, [])

    def test_ambiguous_post_is_not_automatically_retried(self):
        opener = Opener(URLError('sensitive response'))
        api = RunpodAPI('secret-key', opener=opener)
        with self.assertRaises(ActionOutcomeUnknown) as exc:
            api.transition('pod-1', 'start')
        self.assertNotIn('secret', str(exc.exception))
        self.assertEqual(len(opener.requests), 1)
        with self.assertRaises(RunpodAPIError): api.status('pod-1')

    def test_malformed_or_mismatched_response_is_unknown(self):
        for result in (b'not-json', b'{"id":"different"}', b'x' * 2000001):
            with self.subTest(length=len(result)), self.assertRaises(ActionOutcomeUnknown):
                RunpodAPI('test', opener=Opener(result)).transition('pod-1', 'start')

    def test_http_error_exposes_only_status_not_provider_message(self):
        error = HTTPError('https://api.runpod.io', 403, 'secret body', {}, None)
        with self.assertRaises(ActionOutcomeUnknown) as caught:
            RunpodAPI('private-key', opener=Opener(error)).transition('pod-1', 'start')
        self.assertEqual(caught.exception.http_status, 403)
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('private-key', str(caught.exception))


if __name__ == '__main__': unittest.main()
