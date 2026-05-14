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

import getpass
import re
import shlex
import sys
import time
import os
import webbrowser
from dotenv import load_dotenv

import paramiko
from jinja2 import Environment, FileSystemLoader

load_dotenv()

# ---------------------------------------------------------------------
# CONFIGURATION  ---  EDIT THIS SECTION TO MATCH YOUR ENVIRONMENT
# ---------------------------------------------------------------------

SSH_HOST = "dgx-head01.its.albany.edu"
SSH_PORT = 22
BACKEND_JOB_NAME = "Ollama"
OPENCLAW_JOB_NAME = "OpenClaw"
# ---------------------------------------------------------------------
# IMPLEMENTATION
# ---------------------------------------------------------------------

# class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
#     allow_reuse_address = True
#     daemon_threads = True
    
# class ForwardHandler(socketserver.BaseRequestHandler):
#     """
#     Handles one incoming local connection and forwards it over the target SSH transport.
#     """

#     ssh_transport = None
#     remote_host = None
#     remote_port = None

#     def handle(self):
#         try:
#             peer_name = self.request.getpeername()
#         except OSError:
#             peer_name = ("127.0.0.1", 0)

#         try:
#             chan = self.ssh_transport.open_channel(
#                 kind="direct-tcpip",
#                 dest_addr=(self.remote_host, self.remote_port),
#                 src_addr=peer_name,
#             )
#         except Exception as exc:
#             print(f"[ERROR] Could not open SSH channel to {self.remote_host}:{self.remote_port}: {exc}", file=sys.stderr)
#             return

#         if chan is None:
#             print(f"[ERROR] SSH server rejected tunnel to {self.remote_host}:{self.remote_port}", file=sys.stderr)
#             return

#         print(f"[INFO] Forwarding connection from {peer_name} to {self.remote_host}:{self.remote_port}")

#         try:
#             while True:
#                 readable, _, _ = select.select([self.request, chan], [], [])

#                 if self.request in readable:
#                     data = self.request.recv(16384)
#                     if not data:
#                         break
#                     chan.sendall(data)

#                 if chan in readable:
#                     data = chan.recv(16384)
#                     if not data:
#                         break
#                     self.request.sendall(data)

#         finally:
#             chan.close()
#             self.request.close()
#             print(f"[INFO] Closed connection from {peer_name}")
#             input("Press Enter to exit...") 


def get_credentials():
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    folder = input("Folder (optional): ").strip()
    if folder == "":
        folder = f"dgx_aiworkshop_lab/{username}"
    if not username or not password:
        sys.exit("Username and password are required.")
    return username, password, folder


def ssh_connect(host, port, username, password, sock=None):
    try:
        print(f"Connecting to {host}:{port} as {username}...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
                    host, port=port, username=username, password=password, sock=sock,    
            look_for_keys=False, allow_agent=False,
        )
        return client
    except Exception as e:
        print(f"SSH connection failed: {e}")
        input("Press Enter to exit...")
    

def run_remote_script1(client, script_text, label):
    """Upload script_text to /tmp on the server, execute it, return stdout."""
    username =client.get_transport().get_username()
    remote_path = f"auto_{label}_{int(time.time())}.sh"
    sftp = client.open_sftp()

    # Check if there is a model running? If so, kill it before starting a new one.
    _, stdout, stderr = client.exec_command(f"bash -lc 'squeue -u {username} | grep {BACKEND_JOB_NAME}'")
    print(f"Checking for existing {BACKEND_JOB_NAME} jobs...")
    commandOutput= stdout.read().decode("utf-8", errors="replace")
    print(f"squeue output:\n{commandOutput}")
    jobIDs = re.findall(r'^\s*(\d+)', commandOutput, re.MULTILINE)
    if jobIDs:
        print(f"Found existing jobs for {BACKEND_JOB_NAME}: {', '.join(jobIDs)}. Cancelling them...")
        for job in jobIDs:
            _, stdout, stderr = client.exec_command(f"bash -lc 'scancel {job}'")
            print(f"Cancelled existing job {job} for {BACKEND_JOB_NAME}.")
            print(f"Cancelled job outpu: \n {stdout.read().decode('utf-8', errors='replace')}")
        print("Cancelled all existing jobs...")
    print("Starting New Job...")

    # create a new job for the backend, and capture its output to get the host:port.
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
    username =client.get_transport().get_username()
    remote_path = f"auto_{label}_{int(time.time())}.sh"
    sftp = client.open_sftp()

    # Check if there is a model running? If so, kill it before starting a new one.
    _, stdout, stderr = client.exec_command(f"bash -lc 'squeue -u {username} | grep {OPENCLAW_JOB_NAME}'")
    print(f"Checking for existing {OPENCLAW_JOB_NAME} jobs...")
    commandOutput= stdout.read().decode("utf-8", errors="replace")
    print(f"squeue output:\n{commandOutput}")
    jobIDs = re.findall(r'^\s*(\d+)', commandOutput, re.MULTILINE)
    if jobIDs:
        print(f"Found existing jobs for {OPENCLAW_JOB_NAME}: {', '.join(jobIDs)}. Cancelling them...")
        for job in jobIDs:
            _, stdout, stderr = client.exec_command(f"bash -lc 'scancel {job}'")
            print(f"Cancelled existing job {job} for {OPENCLAW_JOB_NAME}.")
            print(f"Cancelled job output: {stdout.read().decode('utf-8', errors='replace')}")
        print("Cancelled all existing jobs...")
    print("Starting New Job...")
    
    # create a new job for the frontend, and capture its output to get the host:port.

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
    _, stdout, stderr = client.exec_command(f"rm ~/{remote_path}")
    
    return command



def run_local_and_open_browser(command, username=None, password=None):
    tokens = shlex.split(command)

    SSH_USER = username
    SSH_PASSWORD = password
    REMOTE_HOST = tokens[-2].split('@')[-1].split(':')[1]
    # tokens[tokens.index('-J') + 1].split('@')[1].split(':')[0]
    SSH_PORT = 22
    SSH_HOST = tokens[-1].split('@')[-1].split(':')[0]
    target_port = 22
    local_bind_host = 'localhost'
    LOCAL_PORT =  int(tokens[tokens.index('-L') + 1].split(':')[0])
    REMOTE_PORT = int(tokens[tokens.index('-L') + 1].split(':')[2])
    remote_bind_host = 'localhost'
    server = None
    jump_client = None
    target_client = None
    from sshTunnel import ForwardHandler, ForwardServer
    
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Use AutoAddPolicy only if you accept the risk on first connect
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    client.connect(
        hostname=SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        password=SSH_PASSWORD,
        allow_agent=True,
        look_for_keys=True,
    )

    transport = client.get_transport()
    transport.set_keepalive(30)

    server = ForwardServer(("127.0.0.1", LOCAL_PORT), ForwardHandler)
    server.ssh_transport = transport
    server.remote_host = REMOTE_HOST
    server.remote_port = REMOTE_PORT

    print(f"Running OpenClaw at: 127.0.0.1:{LOCAL_PORT}/chat?token=1234 "
          f"via {SSH_USER}@{SSH_HOST}  (Ctrl+C to stop)")
    
    try:
        url = "http://" + local_bind_host + ":" + str(LOCAL_PORT)+"/chat?token=1234"
        print(webbrowser.open_new(url=url))
        server.serve_forever()       # this is the equivalent of `-N`
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        client.close()

def main():
    username = os.getenv('username')
    password = os.getenv('password')
    folder = os.getenv('folder')
    if not username or not password or not folder:
        username, password, folder = get_credentials()

    client = ssh_connect(SSH_HOST, SSH_PORT, username, password)
    try:
        environment = Environment(loader=FileSystemLoader("templates/"))
        backendTemplate = environment.get_template("ollama.sh")
        script_one = backendTemplate.render(DGX_FOLDER_NAME=folder, JOB_NAME = BACKEND_JOB_NAME)
        out_one = run_remote_script1(client, script_one, "stage1")
        print(f"--- stage1 output ---\n{out_one}\n---------------------\n")

        backendTemplate = environment.get_template("openclaw-v3.slurm", )
        script_two = backendTemplate.render(DGX_BACKEND_HOST=out_one, JOB_NAME = OPENCLAW_JOB_NAME, DGX_FOLDER_NAME=folder)
        command = run_remote_script2(client, script_two, "stage2")
        print(f"--- stage2 output ---\n{command}\n---------------------\n")

    finally:
        client.close()
    # command = 'ssh -N -L 20044:dgx01.its.albany.edu:20044 a_lt796438@dgx-head01.its.albany.edu'
    run_local_and_open_browser(command, 'a_lt796438', 'premise#Thigh6hence$')

if __name__ == "__main__":
    main()