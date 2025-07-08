The file [`scrcpy_python_client.py`](scrcpy_python_client.py) contains a
minimal implementation of the scrcpy protocol in Python. It exposes a
`Client` class which pushes the server to the device via `adb`, forwards a TCP
port, then connects to the server and decodes the H.264/H.265/AV1 stream with
[PyAV](https://pyav.org/).


Run the client like so:

```bash
python python_client.py
```

You may also stream asynchronously:

```python
from examples.python_client import Client
client = Client()
client.start()  # run in background
client.join()
```

By default the script looks for `scrcpy-server-v3.3.1` in the current
directory, but you may pass `--server` to provide another path. The server JAR
must match the client version (see the
[releases page](https://github.com/Genymobile/scrcpy/releases) to download it).
