"""Run on VPS in the installed Hermes interpreter; no network or messages."""
import sys
from types import SimpleNamespace
sys.path.insert(0,'/usr/local/lib/hermes-agent')
from gateway.run_inbound import GatewayInboundMixin
from gateway.platforms.event import MessageType

for kind,mime in [(MessageType.AUDIO,'audio/mp4'),(MessageType.DOCUMENT,'audio/mp4')]:
    event=SimpleNamespace(message_type=kind,media_urls=['/synthetic/call.m4a'],media_types=[mime])
    images,voice,audio,video=GatewayInboundMixin._classify_inbound_media(event,False)
    assert audio==['/synthetic/call.m4a'] and not voice and not images and not video
event=SimpleNamespace(message_type=MessageType.VOICE,media_urls=['/synthetic/call.ogg'],media_types=['audio/ogg'])
assert GatewayInboundMixin._classify_inbound_media(event,False)[1]==['/synthetic/call.ogg']
print('Telegram audio / document / voice routing: OK')
