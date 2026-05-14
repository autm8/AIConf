#!/usr/bin/env python3
"""
SSH automation script.

Flow:
  1. Prompt the user for a username + password.
  2. SSH into the remote server.
  3. Render TEMPLATE_ONE with the user's credentials, run it on the server,
     capture its output.
  4. Render TEMPLATE_TWO using that output, run it on the server, capture
     its output.
  5. Extract a command from the second script's output, run it locally.
  6. Detect the localhost port and open it in a browser.

Dependency:  pip install paramiko
"""

import subprocess
import getpass
import re
import select
import shlex
import socketserver
import sys
import threading
import time
import webbrowser
import os
from dotenv import load_dotenv


import paramiko
from jinja2 import Environment, FileSystemLoader

load_dotenv()

# ---------------------------------------------------------------------
# CONFIGURATION  ---  EDIT THIS SECTION TO MATCH YOUR ENVIRONMENT
# ---------------------------------------------------------------------

SSH_HOST = "dgx-head01.its.albany.edu"
SSH_PORT = 22

# ---------------------------------------------------------------------
# IMPLEMENTATION
# ---------------------------------------------------------------------

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    
class ForwardHandler(socketserver.BaseRequestHandler):
    """
    Handles one incoming local connection and forwards it over the target SSH transport.
    """

    ssh_transport = None
    remote_host = None
    remote_port = None

    def handle(self):
        try:
            peer_name = self.request.getpeername()
        except OSError:
            peer_name = ("127.0.0.1", 0)

        try:
            chan = self.ssh_transport.open_channel(
                kind="direct-tcpip",
                dest_addr=(self.remote_host, self.remote_port),
                src_addr=peer_name,
            )
        except Exception as exc:
            print(f"[ERROR] Could not open SSH channel to {self.remote_host}:{self.remote_port}: {exc}", file=sys.stderr)
            return

        if chan is None:
            print(f"[ERROR] SSH server rejected tunnel to {self.remote_host}:{self.remote_port}", file=sys.stderr)
            return

        print(f"[INFO] Forwarding connection from {peer_name} to {self.remote_host}:{self.remote_port}")

        try:
            while True:
                readable, _, _ = select.select([self.request, chan], [], [])

                if self.request in readable:
                    data = self.request.recv(16384)
                    if not data:
                        break
                    chan.sendall(data)

                if chan in readable:
                    data = chan.recv(16384)
                    if not data:
                        break
                    self.request.sendall(data)

        finally:
            chan.close()
            self.request.close()
            print(f"[INFO] Closed connection from {peer_name}")



def get_credentials():
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    folder = input("Folder (optional): ").strip()
    if not username or not password:
        sys.exit("Username and password are required.")
    return username, password, folder


def ssh_connect(host, port, username, password, sock=None):
    print(f"Connecting to {host}:{port} as {username}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
                host, port=port, username=username, password=password, sock=sock,    
        look_for_keys=False, allow_agent=False,
    )
    return client


def run_remote_script1(client, script_text, label):
    """Upload script_text to /tmp on the server, execute it, return stdout."""
    remote_path = f"auto_{label}_{int(time.time())}.sh"
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "w") as f:
            f.write(script_text)
    finally:
        sftp.close()
    
    # kick the job off with sbatch, capture the job ID, then poll for the .out file to get the output
    print(f"[remote] running {label}...")
    _, stdout, stderr = client.exec_command(f"bash -lc 'sbatch ~/{remote_path}'")
    out0 = stdout.read().decode("utf-8", errors="replace")
    err0 = stderr.read().decode("utf-8", errors="replace")
    jobID = out0.split(' ')[-1].strip() + '.out'
    print(f"Submitted job {jobID} for {label}.")

    url = None
    
    # check out file for url.
    while not url:
        _, stdout, stderr = client.exec_command(f"cat {jobID} | grep http")
        out0 = stdout.read().decode("utf-8", errors="replace")
        err0 = stderr.read().decode("utf-8", errors="replace")
        m = re.search(r"https?://([^:/\s]+):(\d+)", out0)
        if m:
            host, port = m.group(1), int(m.group(2))
            url = f"http://{host}:{port}"
        time.sleep(1)
        print(f"Waiting for {label} output... {jobID}")
    return url



def run_remote_script2(client, script_text, label):
    """Upload script_text to /tmp on the server, execute it, return stdout."""
    remote_path = f"auto_{label}_{int(time.time())}.sh"
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "w") as f:
            f.write(script_text)
    finally:
        sftp.close()

    print(f"[remote] running {label}...")
    _, stdout, stderr = client.exec_command(f"bash -lc 'sbatch ~/{remote_path}'")
    out0 = stdout.read().decode("utf-8", errors="replace")
    err0 = stderr.read().decode("utf-8", errors="replace")    
    jobID = out0.split(' ')[-1].strip() + '.out'
    print(f"Submitted job {jobID} for {label}.")
    command = None
    
    # check out file for command.
    while not command:
        _, stdout, stderr = client.exec_command(f"cat {jobID} | grep ssh")
        out0 = stdout.read().decode("utf-8", errors="replace")
        err0 = stderr.read().decode("utf-8", errors="replace")
        if len(out0.strip().split('\n')) < 2 :
            time.sleep(1)
            print(f"Waiting for {label} output... {jobID}")
        else:
            command = out0.strip().split('\n')[-1].strip()
    return command



def run_local_and_open_browser(command, username=None, password=None):
    tokens = shlex.split(command)

    username = username
    password = password
    jump_host = tokens[tokens.index('-J') + 1].split('@')[1].split(':')[0]
    jump_port = 22
    target_host = tokens[-1].split('@')[-1].split(':')[0]
    target_port = 22
    local_bind_host = 'localhost'
    local_bind_port =  int(tokens[tokens.index('-L') + 1].split(':')[0])
    remote_bind_port = int(tokens[tokens.index('-L') + 1].split(':')[2])
    remote_bind_host = 'localhost'
    server = None
    jump_client = None
    target_client = None

    try:
        print(f"[INFO] Connecting to jump host {username}@{jump_host}...")
        jump_client = ssh_connect(
            host=jump_host,
            port=jump_port,
            username=username,
            password=password,
        )

        print(f"[INFO] Opening jump channel to target {target_host}:{target_port}...")
        jump_transport = jump_client.get_transport()
        if jump_transport is None or not jump_transport.is_active():
            raise RuntimeError("Jump host SSH transport is not active")

        jump_channel = jump_transport.open_channel(
            kind="direct-tcpip",
            dest_addr=(target_host, target_port),
            src_addr=("127.0.0.1", 0),
        )

        print(f"[INFO] Connecting to target through jump host: {username}@{target_host}...")
        target_client = ssh_connect(
            host=target_host,
            port=target_port,
            username=username,
            password=password,
            sock=jump_channel,
        )

        target_transport = target_client.get_transport()
        if target_transport is None or not target_transport.is_active():
            raise RuntimeError("Target SSH transport is not active")

        ForwardHandler.ssh_transport = target_transport
        ForwardHandler.remote_host = remote_bind_host
        ForwardHandler.remote_port = remote_bind_port

        server = ThreadedTCPServer(
            (local_bind_host, local_bind_port),
            ForwardHandler,
        )

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        print(
            f"[READY] Local tunnel is active: "
            f"{local_bind_host}:{local_bind_port} -> "
            f"{target_host} -> {remote_bind_host}:{remote_bind_port}"
        )
        webbrowser.open_new("http://" + local_bind_host + ":" + str(local_bind_port))
        print("[INFO] Press Ctrl+C to stop.")

        while True:
            time.sleep(3600)
            print(f"[INFO] Url: {"http://" + local_bind_host + ":" + str(local_bind_port)} is still active...")
            print("[INFO] Press Ctrl+C to stop.")

    except KeyboardInterrupt:
        print("\n[INFO] Stopping tunnel...")

    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

        if target_client is not None:
            target_client.close()

        if jump_client is not None:
            jump_client.close()

        print("[INFO] Done.")

def main():
    username = os.getenv('username')
    password = os.getenv('password')
    folder = os.getenv('folder')
    if not username or not password:
        username, password, folder = get_credentials()

    client = ssh_connect(SSH_HOST, SSH_PORT, username, password)
    try:
        environment = Environment(loader=FileSystemLoader("templates/"))
        backendTemplate = environment.get_template("ollama.sh")
        script_one = backendTemplate.render(DGX_FOLDER_NAME=folder)
        out_one = run_remote_script1(client, script_one, "stage1")
        print(f"--- stage1 output ---\n{out_one}\n---------------------\n")

        # --- build -------------------------------------------------------------
        skip_build = os.getenv('skip_build', 'True').lower() == 'true'
        if not skip_build:
            env = {**os.environ, "DOCKER_BUILDKIT": "1"}
            build = ["docker", "build", "-t", "openclaw:2026.5.4", str(".")]
            print("$", " ".join(build), flush=True)
            subprocess.run(build, check=True, env=env)
        # --- run ---------------------------------------------------------------
        run_cmd = [
            "docker", "run", "--rm", "-it",
            "-e", f"OLLAMA_HOST={out_one}",
            "-e", f"OPENCLAW_PORT=2026",
            "-p", "2026:2026",
            "-v", "./data:/mnt/dgx_lab",
            "openclaw:2026.5.4",
        ]
        print("$", " ".join(run_cmd), flush=True)
    
        # Replace this Python process with docker so the TTY, signals (Ctrl+C),
        # stdout/stderr, and exit code behave exactly like a direct `docker run`.
        os.execvp(run_cmd[0], run_cmd)

        # backendTemplate = environment.get_template("openclaw_sbatch.sh")
        # script_two = backendTemplate.render(DGX_BACKEND_HOST=out_one)
        # command = run_remote_script2(client, script_two, "stage2")
        # print(f"--- stage2 output ---\n{command}\n---------------------\n")

    finally:
        client.close()
    # command = 'ssh -N -L 29040:localhost:29040 -J a_lt796438@dgx-head01.its.albany.edu a_lt796438@dgx10.its.albany.edu'
    # run_local_and_open_browser(command, username, password)

if __name__ == "__main__":
    main()