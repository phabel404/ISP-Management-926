"""RouterOS adapter abstraction.

RealAdapter tries a TCP connect to the MikroTik API port (default 8728).
If it cannot reach the router, DemoAdapter supplies clearly-labelled demo
telemetry so the UI never pretends live data exists.
"""
import socket, random, datetime

class RouterStatus:
    def __init__(self, reachable, mode, identity="", version="", uptime="", cpu=0.0, mem=0.0):
        self.reachable = reachable
        self.mode = mode          # "REAL" or "DEMO"
        self.identity = identity
        self.version = version
        self.uptime = uptime
        self.cpu = cpu
        self.mem = mem

class BaseAdapter:
    name = "base"
    def probe(self, host, port=8728, timeout=1.5) -> RouterStatus:
        raise NotImplementedError

class RealAdapter(BaseAdapter):
    """Minimal reachability probe for the RouterOS API port.

    NOTE: full RouterOS API protocol login/query is intentionally not
    implemented here; when the port is open we report REAL-reachability
    with basic info only. Replace with librouteros for full telemetry."""
    name = "real"
    def probe(self, host, port=8728, timeout=1.5):
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            return RouterStatus(True, "REAL", identity="terhubung-api", version="(login belum diimplementasi)",
                                uptime="-", cpu=0.0, mem=0.0)
        except Exception as e:
            return RouterStatus(False, "DEMO", version=str(e))

class DemoAdapter(BaseAdapter):
    name = "demo"
    def probe(self, host, port=8728, timeout=1.5):
        rnd = random.Random(hash(host) & 0xffff + datetime.datetime.now().minute)
        up = rnd.random() > 0.25
        if not up:
            return RouterStatus(False, "DEMO")
        return RouterStatus(True, "DEMO",
                            identity=f"rb-{rnd.randint(1000,9999)}",
                            version=rnd.choice(["7.14.3","7.15.2","6.49.7"]),
                            uptime=f"{rnd.randint(1,200)}d {rnd.randint(0,23)}:{rnd.randint(10,59)}:{rnd.randint(10,59)}",
                            cpu=round(rnd.uniform(3,70),1), mem=round(rnd.uniform(20,80),1))

def get_adapter(prefer="demo"):
    return RealAdapter() if prefer == "real" else DemoAdapter()
