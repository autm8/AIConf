import paramiko
import select
import socketserver
import threading

SSH_HOST = "dgx-head01.its.albany.edu"
SSH_PORT = 22
SSH_USER = "a_lt796438"

LOCAL_PORT  = 20044
REMOTE_HOST = "dgx01.its.albany.edu"
REMOTE_PORT = 20044


class ForwardHandler(socketserver.BaseRequestHandler):
    # transport and remote target injected via the server instance
    def handle(self):
        try:
            chan = self.server.ssh_transport.open_channel(
                "direct-tcpip",
                (self.server.remote_host, self.server.remote_port),
                self.request.getpeername(),
            )
        except Exception as e:
            print(f"open_channel failed: {e}")
            return
        if chan is None:
            print("Channel request rejected by server")
            return

        try:
            while True:
                r, _, _ = select.select([self.request, chan], [], [])
                if self.request in r:
                    data = self.request.recv(4096)
                    if not data:
                        break
                    chan.send(data)
                if chan in r:
                    data = chan.recv(4096)
                    if not data:
                        break
                    self.request.send(data)
        finally:
            chan.close()
            self.request.close()


class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True