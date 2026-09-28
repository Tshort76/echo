"""Library defaults — plain constants, never read from the environment.

Every one of these is also a parameter on the call that uses it. The app
(``echo_app.constants``) reads ``.env`` and passes its values in; the library
itself reads no configuration file and changes nothing in ``os.environ``.
"""

from __future__ import annotations

ENGINE = "edge"
#: Speed is baked into the audio, so 1.0 leaves a file that players can still
#: speed up; a 1.25x file is 1.25x forever.
SPEED = 1.0
#: Largest utterance, in characters, before the engine's own ``max_chars`` applies.
CHUNK_SIZE = 8000
#: Attempts per utterance before synthesis gives up. Engines fail transiently
#: (edge-tts websocket 403s, cloud rate limits); one bad chunk should not cost
#: an hour of work.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
#: Bitrate whenever the output is re-encoded (always for M4B; for MP3 only when
#: the chunks are not already MP3 or a speed change is applied).
BITRATE = "64k"
