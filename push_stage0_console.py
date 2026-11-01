#!/usr/bin/env python3
"""Bootstrap stage0-base onto vJunos consoles over telnet (offline lab).

A fresh vJunos has no fxp0 address, so stage0 must be loaded over the console
before push_lab_configs.py can take over on SSH. This drives that one console
step for the nodes named on the command line (default: all vJunos nodes).

Run from a host that can reach the GNS3 console ports (the workstation on the
same LAN as the server). Console TCP ports are read live from the GNS3 API so
they track the current project. Each node gets a full transcript in
<NODE>.console.log for debugging.

    python push_stage0_console.py PE1          # test one node
    python push_stage0_console.py              # all nodes
    python push_stage0_console.py --probe PE1  # report console state, change nothing
"""
import csv, os, re, socket, subprocess, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.environ.get("GNS3_HOST", "10.1.1.5")
PROJECT = os.environ.get("GNS3_PROJECT", "SR-MPLS-Training")
LOGIN_PW = os.environ.get("LAB_PASSWORD", "labpassword")
BOOT_WAIT = int(os.environ.get("BOOT_WAIT", "900"))   # seconds to wait for login:
PING_WAIT = int(os.environ.get("PING_WAIT", "180"))   # seconds for fxp0 to answer
ORDER = ["PE1", "PE2", "C1", "C2", "CE1", "CE2"]


def load_nodes():
    with open(os.path.join(HERE, "training-nodes.csv")) as f:
        return {r["hostname"]: r for r in csv.DictReader(f)}


def get_consoles():
    base = f"http://{SERVER}:3080/v2"
    projs = requests.get(base + "/projects", timeout=10).json()
    match = [p for p in projs if p["name"] == PROJECT]
    if not match:
        sys.exit(f"project {PROJECT!r} not found on {SERVER}")
    pid = match[0]["project_id"]
    nodes = requests.get(base + f"/projects/{pid}/nodes", timeout=10).json()
    return {n["name"]: n["console"] for n in nodes if n.get("console")}


def stage0_lines(host):
    out = []
    with open(os.path.join(HERE, "configs", "stage0-base", host + ".set")) as f:
        for line in f:
            c = line.split("#")[0].strip()
            if c:
                out.append(c)
    return out


# Telnet control bytes (GNS3 consoles negotiate options we simply refuse).
IAC, SE, SB, WILL, WONT, DO, DONT = 0xFF, 0xF0, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE


class Console:
    def __init__(self, host, port, log):
        self.s = socket.create_connection((host, port), timeout=10)
        self.buf = ""
        self.raw = b""
        self.log = log

    def _drain(self):
        """Strip/answer telnet IAC sequences; return decoded application text."""
        out = bytearray()
        resp = bytearray()
        raw = self.raw
        n = len(raw)
        i = 0
        while i < n:
            b = raw[i]
            if b != IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= n:
                break  # incomplete IAC, keep for next read
            cmd = raw[i + 1]
            if cmd in (DO, DONT, WILL, WONT):
                if i + 2 >= n:
                    break
                opt = raw[i + 2]
                if cmd == DO:
                    resp += bytes([IAC, WONT, opt])
                elif cmd == WILL:
                    resp += bytes([IAC, DONT, opt])
                i += 3
            elif cmd == SB:
                j = i + 2
                while j + 1 < n and not (raw[j] == IAC and raw[j + 1] == SE):
                    j += 1
                if j + 1 >= n:
                    break
                i = j + 2
            elif cmd == IAC:
                out.append(IAC)
                i += 2
            else:
                i += 2  # 2-byte command (NOP, etc.)
        self.raw = raw[i:]
        if resp:
            try:
                self.s.sendall(bytes(resp))
            except OSError:
                pass
        return out.decode(errors="replace")

    def read(self, t=1.0):
        self.s.settimeout(t)
        try:
            d = self.s.recv(4096)
        except socket.timeout:
            d = b""
        if d:
            self.raw += d
        txt = self._drain()
        if txt:
            self.buf += txt
            self.log.write(txt)
            self.log.flush()
        return txt

    def expect(self, pattern, timeout=60):
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            m = rx.search(self.buf)
            if m:
                self.buf = self.buf[m.end():]
                return m
            self.read(1.0)
        return None

    def send(self, s):
        self.s.sendall(s.encode())

    def line(self, s=""):
        self.send(s + "\r")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def wait_ready(c):
    """Wait for a *stable* Junos prompt within BOOT_WAIT. Only the RE 'login:',
    a config '[edit]#', or an operational '@host>' count as ready -- a bare '#'
    is ignored so the FPC's Linux boot shell (root@VMX-FPC0:~#) is not mistaken
    for readiness. Returns 'login' | 'conf' | 'cli' | None."""
    end = time.time() + BOOT_WAIT
    while time.time() < end:
        c.line()
        c.read(2.5)
        tail = c.buf.rstrip()
        if tail.endswith("login:"):
            return "login"
        if "[edit]" in c.buf[-400:] and tail.endswith("#"):
            return "conf"
        if re.search(r"@[\w.-]+>\s*$", c.buf):
            return "cli"
        # RE root shell (root@:~ #); exclude the FPC boot shell (root@VMX-FPC0:~#).
        if re.search(r"root@(?!VMX)[\w.-]*:~\s*[#%]\s*$", c.buf):
            return "shell"
        if len(c.buf) > 40000:
            c.buf = c.buf[-4000:]
    return None


def login(c):
    """Log in as root. A fresh vJunos drops straight to the shell with no
    password prompt (root@:~ #); an already-configured node asks for
    LAB_PASSWORD. Returns True once at the root shell."""
    for pw in ("", LOGIN_PW):
        c.buf = ""
        c.line()
        if not c.expect(r"login:", 25):
            continue
        c.line("root")
        r = c.expect(r"(Password:|Login incorrect|[#%>]\s*$)", 25)
        if not r:
            continue
        if "Password:" in r.group(0):
            c.line(pw)
            r2 = c.expect(r"(Login incorrect|[#%>]\s*$)", 25)
            if not r2 or "Login incorrect" in r2.group(0):
                continue
        elif "Login incorrect" in r.group(0):
            continue
        return True
    return False


def reach_operational(c, state):
    """From the wait_ready state, get to operational mode '>'. Returns True/False."""
    if state == "cli":
        return True
    if state == "conf":
        c.line("exit configuration-mode")
        return bool(c.expect(r">\s*$", 30))
    if state == "shell":
        c.line("cli")                  # already-logged-in root shell -> CLI
        return bool(c.expect(r">\s*$", 30))
    # state == 'login'
    if not login(c):
        return False
    c.line("cli")                      # root shell -> operational CLI
    return bool(c.expect(r">\s*$", 30))


def bootstrap(host, port, mgmt):
    logpath = os.path.join(HERE, f"{host}.console.log")
    with open(logpath, "w") as log:
        c = Console(SERVER, port, log)
        try:
            state = wait_ready(c)
            if state is None:
                return f"FAILED {host}: no Junos prompt within {BOOT_WAIT}s (still booting?) -> {host}.console.log"
            if not reach_operational(c, state):
                return f"FAILED {host}: could not reach operational CLI -> {host}.console.log"
            c.line("configure")
            if not c.expect(r"#\s*$", 30):
                return f"FAILED {host}: could not enter configure -> {host}.console.log"
            c.line("rollback 0")     # clean baseline: drop any stale candidate
            c.expect(r"#\s*$", 30)
            c.line("load set terminal")
            c.expect(r"(\]|\^D|end input)", 10)
            for ln in stage0_lines(host):
                c.line(ln)
                time.sleep(0.04)
            c.read(2.0)
            c.send("\x04")  # Ctrl-D ends load-terminal input
            if not c.expect(r"(load complete|#\s*$)", 45):
                return f"FAILED {host}: load set terminal did not complete -> {host}.console.log"
            c.line("commit and-quit")
            r = c.expect(r"(commit complete|error:|[%>]\s*$)", 180)
            if r and "error:" in r.group(0).lower():
                return f"FAILED {host}: commit error -> {host}.console.log"
            c.expect(r">\s*$", 20)
            # Definitive check: can this host reach fxp0 now that stage0 is committed?
            # fxp0 comes up well after `commit complete` returns -- the address is
            # in the config before the interface is ready to answer ARP. A tight
            # loop here reported PARTIAL on every node of a run that was in fact
            # completely successful, so give it a real deadline instead of a
            # fixed number of fast retries.
            ok = False
            deadline = time.time() + PING_WAIT
            while time.time() < deadline:
                if subprocess.run(["ping", "-c", "1", "-W", "2", mgmt],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0:
                    ok = True
                    break
                time.sleep(3)
            if ok:
                return f"OK {host}: fxp0 {mgmt} reachable -> {host}.console.log"
            return (f"PARTIAL {host}: committed, but fxp0 {mgmt} did not answer within "
                    f"{PING_WAIT}s -> {host}.console.log")
        finally:
            c.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    probe = "--probe" in sys.argv
    nodes = load_nodes()
    consoles = get_consoles()
    targets = args if args else [n for n in ORDER if n in nodes]

    if probe:
        for host in targets:
            with open(os.path.join(HERE, f"{host}.console.log"), "a") as log:
                c = Console(SERVER, consoles[host], log)
                c.line()
                c.read(4.0)
                tail = "\n".join(c.buf.splitlines()[-3:]).strip() or "(no output)"
                c.close()
                print(f"{host} (:{consoles[host]}): {tail!r}")
        return

    for host in targets:
        if host not in consoles:
            print(f"SKIP {host}: no console port from API")
            continue
        print(f"--- {host} (console :{consoles[host]}) ---", flush=True)
        print(bootstrap(host, consoles[host], nodes[host]["mgmt_ip"]), flush=True)


if __name__ == "__main__":
    main()
