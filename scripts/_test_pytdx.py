"""测试 Pytdx IP 连通性"""
import sys
sys.path.insert(0, "d:/lixl/dev/project/private/data_worker")
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pytdx.hq import TdxHq_API
import time

ips = [
    ("119.147.212.81", 7709),
    ("218.75.126.9", 7709),
    ("180.153.18.170", 7709),
    ("180.153.18.171", 7709),
    ("115.238.56.52", 7709),
    ("115.238.56.53", 7709),
]

for ip, port in ips:
    try:
        api = TdxHq_API()
        ok = api.connect(ip, port, time_out=3)
        if ok and api.client is not None:
            print(f"OK {ip}:{port}")
            api.disconnect()
        else:
            print(f"NO {ip}:{port}")
    except Exception as e:
        print(f"ER {ip}:{port} {type(e).__name__}")
    time.sleep(0.5)
