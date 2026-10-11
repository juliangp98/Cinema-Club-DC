"""A stand-in for Groq's client: a model catalogue, scripted replies, and the
real exception types (so ai.py's handling is exercised as written)."""
import types, httpx
from groq import RateLimitError, NotFoundError, BadRequestError

def _err(cls, status, msg, headers=None):
    req = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
    return cls(msg, response=httpx.Response(status, request=req, headers=headers or {}), body={'error': {'message': msg}})

class Fake:
    def __init__(self, models):
        self.models_ = models               # ids, in any order
        self.limited, self.gone, self.empty = set(), set(), set()
        self.calls = []
        self.reply = lambda model, messages, kw: f'reply from {model}'
        fake = self
        class Models:
            def list(self):
                return types.SimpleNamespace(data=[types.SimpleNamespace(id=m, context_window=131072, active=True,
                                                                         input_modalities=['text'], output_modalities=['text'])
                                                   for m in fake.models_ if m not in fake.gone])
        class Completions:
            def create(self, model, max_tokens, messages, **kw):
                fake.calls.append((model, messages[-1]['content'][:40], kw))
                if model in fake.gone:
                    raise _err(NotFoundError, 404, f'The model `{model}` model_decommissioned')
                if model in fake.limited:
                    raise _err(RateLimitError, 429, 'Rate limit reached. Please try again in 11m12.5s.')
                text = '' if model in fake.empty else fake.reply(model, messages, kw)
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])
        self.models = Models()
        self.chat = types.SimpleNamespace(completions=Completions())